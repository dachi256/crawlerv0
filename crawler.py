import os
import json
import time
import argparse
import urllib.parse
import csv
import re
from playwright.sync_api import sync_playwright, TimeoutError

# Configuration parameters
PAGE_LOAD_TIMEOUT = 15000
WAIT_TIME = 2

# Common tracking domains for rule-based detection
TRACKING_DOMAINS = [
    'google-analytics.com',
    'googletagmanager.com',
    'doubleclick.net',
    'facebook.net',
    'facebook.com/tr',
    'adnxs.com',
    'adsrvr.org',
    'scorecardresearch.com',
    'amazon-adsystem.com',
    'analytics.twitter.com',
    'ads.linkedin.com',
    'adroll.com',
    'bing.com/bat',
]

# Tracking-related keywords in URL paths
TRACKING_PATH_KEYWORDS = [
    '/analytics',
    '/collect',
    '/pixel',
    '/tracker',
    '/track',
    '/beacon',
    '/event',
    '/conversion',
    '/impression',
    '/stats'
]

# Tracking-related query parameters
TRACKING_QUERY_PARAMS = [
    'fbclid',
    'utm_',
    'cid',
    'gclid',
    'dclid',
    'fbid',
    'userid',
    'tracking_id',
    'visitor_id',
    'msclkid',
]

def get_domain(url):
    """Extract the domain from a URL."""
    parsed_url = urllib.parse.urlparse(url)
    domain = parsed_url.netloc
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain

def is_tracking_request(url):
    """
    Determine if a URL is a tracking request based on three rules:
    1. Domain is a known tracker
    2. URL path contains tracking keywords
    3. Query parameters suggest tracking
    """
    parsed_url = urllib.parse.urlparse(url)
    domain = parsed_url.netloc
    path = parsed_url.path.lower()
    query = parsed_url.query
    
    # Rule 1: Check against known tracker domains
    for tracker_domain in TRACKING_DOMAINS:
        if tracker_domain in domain:
            return True
    
    # Rule 2: Check URL path for tracking-related keywords
    for keyword in TRACKING_PATH_KEYWORDS:
        if keyword in path:
            return True
    
    # Rule 3: Check for tracking-related query parameters
    query_params = query.split('&')
    for param in query_params:
        for tracking_param in TRACKING_QUERY_PARAMS:
            if param.startswith(tracking_param):
                return True
    
    # Additional check for ad-related subdomains
    ad_subdomains = ['ad', 'ads', 'adservice', 'adserver', 'adtech', 'advertising']
    for subdomain in ad_subdomains:
        if f'{subdomain}.' in domain:
            return True
    
    return False

def handle_consent_banner(page, consent_mode):
    """Attempt to handle consent banners using common selectors."""
    if consent_mode != "accept":
        return "no-consent-mode"
    
    # Common accept buttons
    accept_selectors = [
        "button:text-is('Accept')", 
        "button:text-is('Accept all')",
        "button:text-is('I agree')",
        "button:text-is('Allow')",
        "#onetrust-accept-btn-handler",
        "[id*='accept']",
        "button:has-text('Accept')",
        "button:has-text('Accept cookies')",
        "button:has-text('I accept')",
        ".consent-banner button:first-child",
        ".agree-button",
        "[aria-label*='consent']",
        "[aria-label*='cookie']",
        "button:has-text('Agree')",
        "[data-testid='GDPR-accept']",
        "#didomi-notice-agree-button",
        ".css-47sehv",  # CNN specific
        ".fc-button-label",  # Common for many sites
    ]
    
    for selector in accept_selectors:
        try:
            if page.query_selector(selector):
                page.click(selector, timeout=1500)
                return "accepted"
        except:
            continue
    
    return "no-banner"

def crawl_page(url, browser, consent_mode="accept", track_cookies_before_consent=False):
    """
    Crawl a page and collect privacy metrics.
    If track_cookies_before_consent is True, will first measure cookies before consent interaction.
    """
    # Create context with viewport size to ensure desktop layout
    context = browser.new_context(
        viewport={'width': 1280, 'height': 800}
    )
    
    # Tracking data structures
    third_party_domains = set()
    tracking_requests = set()
    main_domain = get_domain(url)
    
    # Cookie tracking
    cookies_before_consent = []
    third_party_cookies_before_consent = []

    def request_monitor(request):
        req_domain = get_domain(request.url)
        if req_domain != main_domain and req_domain:
            third_party_domains.add(req_domain)
            if is_tracking_request(request.url):
                tracking_requests.add(req_domain)

    context.on("request", request_monitor)
    page = context.new_page()

    print(f"\n=== Crawling {url} ===")

    try:
        # Go to URL with timeout
        page.goto(url, timeout=PAGE_LOAD_TIMEOUT, wait_until='domcontentloaded')
        time.sleep(WAIT_TIME)
        
        # If tracking pre-consent cookies, get cookies before banner interaction
        if track_cookies_before_consent:
            cookies_before_consent = context.cookies()
            third_party_cookies_before_consent = [
                cookie for cookie in cookies_before_consent 
                if not cookie["domain"].endswith(main_domain)
            ]
            
            print(f"    Pre-consent cookies: {len(cookies_before_consent)}")
            print(f"    Pre-consent 3P cookies: {len(third_party_cookies_before_consent)}")

        # Handle consent banner with multiple attempts and scrolling
        consent_result = "no-banner"
        if consent_mode == "accept":
            # First try to find banner at current position
            initial_result = handle_consent_banner(page, consent_mode)
            if initial_result == "accepted":
                consent_result = initial_result
            else:
                # Try scrolling down a bit to reveal banners at bottom
                page.evaluate("window.scrollTo(0, 300)")
                time.sleep(1)
                scroll_result = handle_consent_banner(page, consent_mode)
                if scroll_result == "accepted":
                    consent_result = scroll_result
                else:
                    # Some sites only show banner after a delay
                    time.sleep(2)
                    delayed_result = handle_consent_banner(page, consent_mode)
                    if delayed_result == "accepted":
                        consent_result = delayed_result
        else:
            consent_result = "no-consent-mode"
            
        time.sleep(WAIT_TIME)

        # Get cookies and domains after consent interaction
        all_cookies = context.cookies()
        num_cookies = len(all_cookies)
        num_thirdparty = len(third_party_domains)
        num_tracking = len(tracking_requests)
        
        print(f"    Consent Banner: {consent_result}")
        print(f"    Cookies: {num_cookies}, 3P domains: {num_thirdparty}, Tracking: {num_tracking}")

        # Get internal links
        internal_links = []
        try:
            links = page.evaluate('''() => {
                const links = Array.from(document.querySelectorAll('a[href]'));
                return links.map(a => a.href).filter(href => href.startsWith('http'));
            }''')
            
            base_domain = get_domain(url)
            for link in links:
                if get_domain(link) == base_domain:
                    # Skip the homepage or fragment-only URLs
                    if link != url and link != url + "/" and "#" not in link:
                        internal_links.append(link)
                        if len(internal_links) >= 2:
                            break
        except Exception as e:
            print(f"    [!] Error getting links: {str(e)[:100]}")
        
        result = {
            "url": url,
            "consent_result": consent_result,
            "cookies_count": num_cookies,
            "third_party_count": num_thirdparty,
            "tracking_count": num_tracking,
            "tracking_domains": list(tracking_requests),
            "third_party_domains": list(third_party_domains),
            "internal_links": internal_links[:2],
            "pre_consent_cookies": len(third_party_cookies_before_consent) if track_cookies_before_consent else 0,
        }

        return result

    except Exception as e:
        print(f"    [!] Error crawling {url}: {str(e)[:150]}")
        return {
            "url": url,
            "error": str(e),
            "internal_links": []
        }
    finally:
        context.close()

def read_site_list(file_path):
    """Read sites from a file."""
    with open(file_path, 'r') as f:
        sites = [line.strip() for line in f if line.strip()]
    if len(sites) > 10:
        print(f"[!] Found {len(sites)} sites; limiting to 10 as per instructions.")
        sites = sites[:10]
    return sites

def privacy_analysis(site_list_path, consent_mode="accept"):
    """Analyze sites and calculate privacy scores."""
    os.makedirs('output', exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        sites = read_site_list(site_list_path)
        site_results = []
        
        for site in sites:
            if not site.startswith("http"):
                site = "https://" + site
                
            site_data = {
                "site": site,
                "pages": []
            }
            
            # 1. Test homepage first without interacting with consent banner
            print(f"\n--- First checking pre-consent cookies for {site} ---")
            home_pre_consent = crawl_page(
                url=site, 
                browser=browser, 
                consent_mode="none", 
                track_cookies_before_consent=True
            )
            
            # 2. Crawl the homepage normally
            home_result = crawl_page(url=site, browser=browser, consent_mode=consent_mode)
            
            # Add pre-consent cookie data to the result
            home_result["pre_consent_cookies"] = home_pre_consent.get("pre_consent_cookies", 0)
            site_data["pages"].append(home_result)
            
            # 3. Crawl up to 2 internal pages
            internal_links = home_result.get("internal_links", [])[:2]
            for i, internal_link in enumerate(internal_links, 1):
                print(f"\n--- Crawling internal page {i}: {internal_link}")
                internal_result = crawl_page(url=internal_link, browser=browser, consent_mode=consent_mode)
                site_data["pages"].append(internal_result)
            
            # 4. Calculate site metrics
            site_data["metrics"] = calculate_site_metrics(site_data["pages"])
            site_results.append(site_data)
            
            # Short delay between sites
            time.sleep(1)
        
        browser.close()
    
    # Calculate privacy scores
    print("\nCalculating privacy scores...")
    ranked_sites = calculate_privacy_scores(site_results)
    
    # Output privacy ranking
    print("\n=== PRIVACY RANKING ===")
    for i, site_data in enumerate(ranked_sites, 1):
        print(f"{i}. {site_data['site']} - Score: {site_data['privacy_score']:.2f}")
        print(f"   3P domains: {site_data['metrics']['third_party_count']}, " +
              f"Tracking: {site_data['metrics']['tracking_count']}, " +
              f"Cookies: {site_data['metrics']['cookie_count']}, " +
              f"Pre-consent cookies: {site_data['metrics']['pre_consent_cookies']}, " +
              f"Has banner: {site_data['metrics']['has_banner']}")
    
    # Save results
    save_privacy_results(ranked_sites)
    
    return ranked_sites

def calculate_site_metrics(pages):
    """Calculate privacy metrics across all pages for a site."""
    # Track unique domains and requests
    third_party_domains = set()
    tracking_domains = set()
    total_cookies = 0
    has_banner = False
    pre_consent_cookies = 0
    
    for page in pages:
        # Skip pages with errors
        if "error" in page:
            continue
        
        # Add third-party domains
        domains = page.get("third_party_domains", [])
        third_party_domains.update(domains)
        
        # Add tracking domains
        tracking = page.get("tracking_domains", [])
        tracking_domains.update(tracking)
        
        # Add cookies
        total_cookies += page.get("cookies_count", 0)
        
        # Get pre-consent cookies (should only be from homepage)
        if "pre_consent_cookies" in page and page["pre_consent_cookies"] > 0:
            pre_consent_cookies = page["pre_consent_cookies"]
        
        # Check for consent banner
        if page.get("consent_result", "") not in ["no-banner", "no-consent-mode"]:
            has_banner = True
    
    return {
        "third_party_count": len(third_party_domains),
        "tracking_count": len(tracking_domains),
        "cookie_count": total_cookies,
        "has_banner": has_banner,
        "pre_consent_cookies": pre_consent_cookies
    }

def calculate_privacy_scores(site_results):
    """Calculate privacy scores based on five parameters."""
    # Define maximum values for score normalization based on observed data
    MAX_THIRD_PARTY = 220  
    MAX_COOKIES = 600     
    MAX_TRACKING = 50     
    MAX_PRE_CONSENT_COOKIES = 75  
    
    scored_sites = []
    
    for site_data in site_results:
        metrics = site_data["metrics"]
        
        # 1. Third-party score (20% weight)
        third_party_score = max(0, 100 - (metrics["third_party_count"] / MAX_THIRD_PARTY * 100))
        
        # 2. Cookie score (20% weight)
        cookie_score = max(0, 100 - (metrics["cookie_count"] / MAX_COOKIES * 100))
        
        # 3. Banner score (20% weight)
        banner_score = 80 if metrics["has_banner"] else 20
        
        # 4. Tracking requests score (25% weight)
        tracking_score = max(0, 100 - (metrics["tracking_count"] / MAX_TRACKING * 100))
        
        # 5. Pre-consent cookies score (15% weight)
        # Lower score if cookies are set before consent
        pre_consent_score = max(0, 100 - (metrics["pre_consent_cookies"] / MAX_PRE_CONSENT_COOKIES * 100))
        # If a site doesn't have a banner but sets cookies, give it minimum score
        if not metrics["has_banner"] and metrics["cookie_count"] > 0:
            pre_consent_score = 0
 
        # Calculate weighted privacy score
        privacy_score = (
            0.20 * third_party_score +
            0.20 * cookie_score +
            0.20 * banner_score +
            0.25 * tracking_score +
            0.15 * pre_consent_score
        )
        
        scored_sites.append({
            "site": site_data["site"],
            "privacy_score": privacy_score,
            "metrics": metrics,
            "component_scores": {
                "third_party_score": third_party_score,
                "cookie_score": cookie_score,
                "banner_score": banner_score,
                "tracking_score": tracking_score,
                "pre_consent_score": pre_consent_score
            }
        })
    
    # Sort by privacy score (higher is better)
    ranked_sites = sorted(scored_sites, key=lambda x: x["privacy_score"], reverse=True)
    
    return ranked_sites

def save_privacy_results(ranked_sites):
    """Save privacy results to CSV and JSON files."""
    # Save to CSV
    csv_file = "output/privacy_ranking.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        # Write header
        writer.writerow([
            "Rank", "Site", "Privacy Score", 
            "Third-party Domains", "Tracking Domains", "Cookies", 
            "Pre-consent Cookies", "Has Banner"
        ])
        
        # Write data
        for i, site in enumerate(ranked_sites, 1):
            writer.writerow([
                i,
                site["site"],
                f"{site['privacy_score']:.2f}",
                site["metrics"]["third_party_count"],
                site["metrics"]["tracking_count"],
                site["metrics"]["cookie_count"],
                site["metrics"]["pre_consent_cookies"],
                site["metrics"]["has_banner"]
            ])
    
    # Save detailed results to JSON
    json_file = "output/privacy_analysis_results.json"
    with open(json_file, "w") as f:
        json.dump(ranked_sites, f, indent=2)
    
    print(f"\nResults saved to {csv_file} and {json_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Web Privacy Lab 9 Crawler')
    parser.add_argument('-l', '--site_list', type=str, required=True,
                        help='Path to text file containing sites to crawl')
    parser.add_argument('--consent_mode', type=str, choices=['none', 'accept', 'reject'], default='accept',
                        help='How to handle consent banners.')
    parser.add_argument('--privacy_analysis', action='store_true',
                        help='Run privacy analysis')
    
    args = parser.parse_args()
    
    # Run the analysis
    if args.privacy_analysis:
        privacy_analysis(
            site_list_path=args.site_list,
            consent_mode=args.consent_mode
        )
    else:
        print("Please use --privacy_analysis flag to run the required in-lab analysis.")