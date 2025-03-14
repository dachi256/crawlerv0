from playwright.sync_api import sync_playwright, TimeoutError
import os
import json
import time
import argparse
import urllib.parse

def start_browser():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False)  # visible mode
    return playwright, browser

def get_domain(url):
    """Extract the domain from a URL"""
    parsed_url = urllib.parse.urlparse(url)
    domain = parsed_url.netloc
    # Handle cases like 'www.example.com'
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain

def crawl_page(url, browser):
    # Create output directory
    os.makedirs('output', exist_ok=True)
    
    # Prepare site name for file naming
    site_name = url.replace('https://', '').replace('http://', '').split('/')[0].replace('.', '_')
    
    # Create a new context
    context = browser.new_context(
        record_har_path=f'output/{site_name}_recording.har'
    )
    
    page = context.new_page()
    print(f"Navigating to {url}")
    
    try:
        page.goto(url, timeout=60000, wait_until='domcontentloaded')
        
        try:
            page.wait_for_load_state('networkidle', timeout=30000)
        except TimeoutError:
            print("Didn't reach idle, but continuing")
        
        # Store the initial URL to detect navigation later
        initial_url = page.url
        
        # Extract all links with their text content
        links_data = page.evaluate('''() => {
            try {
                const anchors = Array.from(document.querySelectorAll('a'));
                return anchors.map(a => ({
                    href: a.href,
                    text: a.textContent.trim(),
                    visible: a.offsetWidth > 0 && a.offsetHeight > 0 && getComputedStyle(a).visibility !== 'hidden',
                    hasSubmenu: a.classList.contains('dropdown-toggle') || 
                               a.getAttribute('aria-haspopup') === 'true' || 
                               a.querySelector('.dropdown-menu, .submenu') !== null ||
                               a.parentElement.querySelector(':scope > .dropdown-menu, :scope > .submenu') !== null
                }));
            } catch (e) {
                return [];
            }
        }''')
        
        # Filter for valid links
        valid_links = [link for link in links_data if link['href'] and link['href'].startswith('http')]
        
        # Get base domain of the current page
        current_domain = get_domain(url)
        
        # Find first-party links (same domain)
        first_party_links = [link for link in valid_links if get_domain(link['href']) == current_domain and link['visible']]
        
        # Prioritize links: regular links first, then potential dropdown toggles
        regular_links = [link for link in first_party_links if not link['hasSubmenu']]
        dropdown_links = [link for link in first_party_links if link['hasSubmenu']]
        
        # Combine them with regular links first, then dropdown links
        prioritized_links = regular_links + dropdown_links
        
        # Save links to JSON file
        links_file = f'output/{site_name}_links.json'
        with open(links_file, 'w') as f:
            json.dump({
                "url": url, 
                "all_links": [link['href'] for link in valid_links],
                "first_party_links": [link['href'] for link in first_party_links],
                "regular_links": [link['href'] for link in regular_links],
                "dropdown_links": [link['href'] for link in dropdown_links]
            }, f, indent=4)
        
        # Take screenshot of initial page
        initial_screenshot_path = f'output/{site_name}_initial_screenshot.png'
        page.screenshot(path=initial_screenshot_path)
        
        # Try to click on a first-party link
        clicked = False
        click_result = None
        navigated = False
        dropdown_detected = False
        dropdown_clicked = False
        
        if prioritized_links:
            # First attempt: try regular links
            for link in prioritized_links:
                try:
                    print(f"Attempting to click on: {link['text']} ({link['href']})")
                    
                    # Find the link by its href
                    selector = f"a[href='{link['href']}'], a[href*='{link['href'].split('://')[-1]}']"
                    
                    if page.query_selector(selector):
                        # Store if this is a dropdown link
                        is_dropdown = link['hasSubmenu']
                        
                        # Click with a timeout
                        page.click(selector, timeout=10000)
                        
                        # Wait a moment to let any dropdowns or navigation start
                        time.sleep(2)
                        
                        # Check if URL changed (navigation occurred)
                        current_url = page.url
                        navigated = current_url != initial_url
                        
                        # Check for newly visible dropdown menus
                        dropdown_elements = page.query_selector_all('.dropdown-menu[style*="display: block"], .dropdown-menu:not([style*="display: none"])')
                        dropdown_detected = len(dropdown_elements) > 0
                        
                        # Take screenshot after initial click
                        after_click_screenshot_path = f'output/{site_name}_after_click_screenshot.png'
                        page.screenshot(path=after_click_screenshot_path)
                        
                        clicked = True
                        click_result = {
                            "Clicked link": link['href'],
                            "Link text": link['text'],
                            "After-click screenshot": after_click_screenshot_path,
                            "Navigation occurred": navigated,
                            "Dropdown detected": dropdown_detected
                        }
                        
                        # If we found a dropdown but didn't navigate, try clicking an item in the dropdown
                        if dropdown_detected and not navigated:
                            print("Dropdown menu detected, looking for items to click...")
                            
                            # Get dropdown menu items
                            dropdown_items = page.evaluate('''() => {
                                const menus = document.querySelectorAll('.dropdown-menu[style*="display: block"], .dropdown-menu:not([style*="display: none"])');
                                if (menus.length === 0) return [];
                                
                                const menuItems = Array.from(menus[0].querySelectorAll('a'));
                                return menuItems.map(a => ({
                                    href: a.href,
                                    text: a.textContent.trim()
                                }));
                            }''')
                            
                            # Try to click on a dropdown item
                            if dropdown_items:
                                for item in dropdown_items:
                                    try:
                                        print(f"Attempting to click dropdown item: {item['text']} ({item['href']})")
                                        
                                        # Use text content for more reliable selector
                                        item_selector = f"a[href='{item['href']}'], a:text('{item['text']}')"
                                        
                                        if page.query_selector(item_selector):
                                            # Click the dropdown item
                                            page.click(item_selector, timeout=10000)
                                            
                                            # Wait for navigation
                                            page.wait_for_load_state('domcontentloaded', timeout=30000)
                                            
                                            try:
                                                page.wait_for_load_state('networkidle', timeout=10000)
                                            except TimeoutError:
                                                print("Network didn't reach idle after dropdown click, but continuing")
                                            
                                            time.sleep(3)  # Give time to load
                                            
                                            # Check if URL changed after dropdown item click
                                            final_url = page.url
                                            dropdown_navigated = final_url != current_url
                                            
                                            # Take final screenshot
                                            dropdown_screenshot_path = f'output/{site_name}_after_dropdown_click_screenshot.png'
                                            page.screenshot(path=dropdown_screenshot_path)
                                            
                                            dropdown_clicked = True
                                            click_result.update({
                                                "Dropdown item clicked": item['href'],
                                                "Dropdown item text": item['text'],
                                                "After-dropdown-click screenshot": dropdown_screenshot_path,
                                                "Dropdown navigation occurred": dropdown_navigated
                                            })
                                            break
                                    except Exception as dropdown_error:
                                        print(f"Failed to click dropdown item {item['href']}: {dropdown_error}")
                        
                        break  # Exit the loop after first successful click
                        
                except Exception as click_error:
                    print(f"Failed to click on {link['href']}: {click_error}")
            
            if not clicked:
                print("No clickable first-party links found or all click attempts failed")
        else:
            print("No first-party links found")
        
        time.sleep(3)  # Wait to see the page
        
        result = {
            "Crawled url": url, 
            "Links saved to": links_file,
            "HAR file": f'output/{site_name}_recording.har',
            "Initial screenshot": initial_screenshot_path,
            "All links count": len(valid_links),
            "First-party links count": len(first_party_links),
            "Regular links count": len(regular_links),
            "Dropdown links count": len(dropdown_links),
            "First-party link clicked": clicked
        }
        
        if click_result:
            result.update(click_result)
            
        return result
    
    except Exception as e:
        print(f"Error crawling {url}: {e}")
        # Try to take a screenshot even if there was an error
        try:
            screenshot_path = f'output/{site_name}_error_screenshot.png'
            page.screenshot(path=screenshot_path)
            print(f"Saved error screenshot to {screenshot_path}")
        except:
            pass
        return {
            "Crawled url": url,
            "Error": str(e)
        }
    finally:
        context.close()  # Close context which saves the HAR file

def read_site_list(file_path):
    with open(file_path, 'r') as f:
        # Read lines and remove whitespace, empty lines
        sites = [line.strip() for line in f.readlines() if line.strip()]
    return sites

def crawl_sites_from_list(site_list_path):
    playwright, browser = start_browser()
    
    try:
        # Read sites from file
        sites = read_site_list(site_list_path)
        
        # Limit to 10 sites as per lab instructions
        if len(sites) > 10:
            print(f"Warning: List contains {len(sites)} sites. Limiting to first 10 as per lab instructions.")
            sites = sites[:10]
        
        results = []
        
        # Crawl each site
        for site in sites:
            # Ensure URL has protocol
            if not site.startswith('http'):
                site = 'https://' + site
            
            # Crawl the site
            result = crawl_page(site, browser)
            results.append(result)
            
            # Wait between requests to avoid overloading servers
            time.sleep(5)
        
        # Save overall results
        with open('output/crawl_results.json', 'w') as f:
            json.dump(results, f, indent=4)
            
        return results
    
    finally:
        browser.close()
        playwright.stop()

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Web crawler using Playwright')
    parser.add_argument('-l', '--site_list', type=str, required=True,
                        help='Path to text file containing list of sites to crawl')
    
    args = parser.parse_args()
    
    # Crawl sites from the provided list
    results = crawl_sites_from_list(args.site_list)
    
    # Print summary of results
    print("\nCrawl Summary:")
    for i, result in enumerate(results, 1):
        print(f"\nSite {i}:")
        for key, value in result.items():
            print(f"  {key}: {value}")