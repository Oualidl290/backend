import requests
from bs4 import BeautifulSoup
import pandas as pd
import logging
import time
import os
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('jewelry_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('jewelry_scraper')

class JewelryScraperConfig:
    """Configuration for the jewelry scraper"""
    # Base URLs and endpoints
    BASE_URL = "https://supplier-jewelry-website.com"
    CATEGORY_URLS = [
        "/necklaces",
        "/earrings",
        "/rings",
        "/bracelets",
        "/pendants"
    ]
    
    # Request headers to mimic browser
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0'
    }
    
    # CSS selectors for product data
    SELECTORS = {
        'product_links': '.product-item a.product-link',
        'pagination': '.pagination a.next',
        'product_title': '.product-title',
        'product_sku': '.product-sku',
        'product_price': '.product-price',
        'product_stock': '.stock-status',
        'product_description': '.product-description',
        'product_images': '.product-gallery img',
        'product_materials': '.materials-list',
        'product_dimensions': '.dimensions',
        'product_weight': '.weight'
    }
    
    # Amazon feed columns
    AMAZON_FEED_COLUMNS = [
        'sku', 'product-id', 'product-id-type', 'title', 'product-type',
        'brand', 'description', 'bullet-point1', 'bullet-point2', 'bullet-point3',
        'bullet-point4', 'bullet-point5', 'main-image-url', 'other-image-url1',
        'other-image-url2', 'other-image-url3', 'other-image-url4',
        'swatch-image-url', 'parent-child', 'parent-sku', 'relationship-type',
        'variation-theme', 'size', 'color', 'material-type', 'style',
        'item-price', 'quantity', 'merchant-shipping-group-name',
        'max-aggregate-ship-quantity', 'condition-type', 'sale-price',
        'item-weight', 'item-weight-unit-of-measure', 'item-dimension-unit', 
        'item-length', 'item-width', 'item-height', 'fulfillment-center-id'
    ]
    
    # Output file paths
    OUTPUT_DIR = "data"
    INVENTORY_FILE = "full_inventory.xlsx"
    OUTOFSTOCK_FILE = "out_of_stock.xlsx"


class JewelryScraper:
    """Scraper for jewelry products from supplier website"""
    
    def __init__(self, config=None):
        self.config = config or JewelryScraperConfig()
        self.session = requests.Session()
        self.session.headers.update(self.config.HEADERS)
        self.products = []
        self.unavailable_products = []
        
        # Ensure output directory exists
        os.makedirs(self.config.OUTPUT_DIR, exist_ok=True)
        
    def get_page(self, url, retries=3, delay=2):
        """Get page content with retry logic"""
        for attempt in range(retries):
            try:
                response = self.session.get(url)
                response.raise_for_status()
                return response.text
            except requests.exceptions.RequestException as e:
                logger.warning(f"Error fetching {url}: {e}. Attempt {attempt+1}/{retries}")
                if attempt < retries - 1:
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to fetch {url} after {retries} attempts")
                    return None
    
    def extract_product_links(self, html):
        """Extract product links from category page"""
        soup = BeautifulSoup(html, 'html.parser')
        product_elements = soup.select(self.config.SELECTORS['product_links'])
        return [elem['href'] if elem['href'].startswith('http') else 
                self.config.BASE_URL + elem['href'] for elem in product_elements]
    
    def get_next_page_url(self, html, current_url):
        """Get URL for next page if pagination exists"""
        soup = BeautifulSoup(html, 'html.parser')
        next_button = soup.select_one(self.config.SELECTORS['pagination'])
        if next_button and next_button.get('href'):
            next_url = next_button['href']
            if not next_url.startswith('http'):
                next_url = self.config.BASE_URL + next_url
            return next_url
        return None
    
    def parse_product_page(self, html, product_url):
        """Extract product details from product page"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Basic product data
        title_elem = soup.select_one(self.config.SELECTORS['product_title'])
        sku_elem = soup.select_one(self.config.SELECTORS['product_sku'])
        price_elem = soup.select_one(self.config.SELECTORS['product_price'])
        stock_elem = soup.select_one(self.config.SELECTORS['product_stock'])
        
        # Exit if critical elements missing
        if not all([title_elem, sku_elem]):
            logger.warning(f"Missing critical product data at {product_url}")
            return None
        
        # Extract stock status
        stock_status = "Available"
        if stock_elem:
            status_text = stock_elem.text.strip().lower()
            if "out of stock" in status_text:
                stock_status = "Out of Stock"
            elif "production" in status_text or "manufacturing" in status_text:
                stock_status = "In Production"
            elif "discontinued" in status_text or "removed" in status_text:
                stock_status = "Removed"
        
        # Extract images
        image_elements = soup.select(self.config.SELECTORS['product_images'])
        images = [img.get('src') or img.get('data-src') for img in image_elements if img.get('src') or img.get('data-src')]
        
        # Extract description
        desc_elem = soup.select_one(self.config.SELECTORS['product_description'])
        description = desc_elem.text.strip() if desc_elem else ""
        
        # Extract materials
        materials_elem = soup.select_one(self.config.SELECTORS['product_materials'])
        materials = materials_elem.text.strip() if materials_elem else ""
        
        # Extract dimensions
        dimensions_elem = soup.select_one(self.config.SELECTORS['product_dimensions'])
        dimensions = dimensions_elem.text.strip() if dimensions_elem else ""
        
        # Extract weight
        weight_elem = soup.select_one(self.config.SELECTORS['product_weight'])
        weight = weight_elem.text.strip() if weight_elem else ""
        
        # Build product data dictionary
        product = {
            'sku': sku_elem.text.strip(),
            'title': title_elem.text.strip(),
            'price': price_elem.text.strip() if price_elem else "",
            'stock_status': stock_status,
            'description': description,
            'materials': materials,
            'dimensions': dimensions,
            'weight': weight,
            'main_image': images[0] if images else "",
            'other_images': images[1:] if len(images) > 1 else [],
            'url': product_url,
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        return product
    
    def scrape_category(self, category_url):
        """Scrape all products from a category"""
        full_url = self.config.BASE_URL + category_url if not category_url.startswith('http') else category_url
        logger.info(f"Scraping category: {full_url}")
        
        product_links = []
        current_url = full_url
        page_count = 1
        
        # Handle pagination
        while current_url:
            logger.info(f"Scraping page {page_count}: {current_url}")
            html = self.get_page(current_url)
            if not html:
                break
                
            # Extract product links from current page
            links = self.extract_product_links(html)
            product_links.extend(links)
            logger.info(f"Found {len(links)} products on page {page_count}")
            
            # Get next page URL if exists
            next_url = self.get_next_page_url(html, current_url)
            if next_url and next_url != current_url:
                current_url = next_url
                page_count += 1
                time.sleep(1)  # Polite delay
            else:
                break
        
        logger.info(f"Total products found in category: {len(product_links)}")
        return product_links
    
    def scrape_all_products(self):
        """Scrape all products from all categories"""
        all_product_links = []
        
        # Get product links from all categories
        for category_url in self.config.CATEGORY_URLS:
            category_links = self.scrape_category(category_url)
            all_product_links.extend(category_links)
        
        # Remove duplicates
        unique_links = list(set(all_product_links))
        logger.info(f"Total unique products found: {len(unique_links)}")
        
        # Process each product
        for i, link in enumerate(unique_links):
            logger.info(f"Processing product {i+1}/{len(unique_links)}: {link}")
            html = self.get_page(link)
            if html:
                product = self.parse_product_page(html, link)
                if product:
                    if product['stock_status'] in ["Out of Stock", "In Production", "Removed"]:
                        self.unavailable_products.append(product)
                    else:
                        self.products.append(product)
            
            # Polite delay to avoid rate limiting
            if i % 10 == 0:
                time.sleep(2)
            else:
                time.sleep(0.5)
        
        logger.info(f"Processed {len(self.products)} available products")
        logger.info(f"Processed {len(self.unavailable_products)} unavailable products")
    
    def map_to_amazon_feed(self, products):
        """Map scraped products to Amazon feed format"""
        amazon_data = []
        
        for product in products:
            # Map product data to Amazon feed format
            amazon_item = {
                'sku': product['sku'],
                'product-id': product['sku'],  # Use SKU as product ID or assign UPC/EAN if available
                'product-id-type': '1',        # 1 for ASIN, 2 for ISBN, 3 for UPC, 4 for EAN
                'title': product['title'],
                'product-type': 'jewelry',     # Specify correct product type for jewelry category
                'brand': 'Your Brand',         # Set your brand name
                'description': product['description'],
                'bullet-point1': f"Material: {product['materials']}",
                'bullet-point2': f"Dimensions: {product['dimensions']}",
                'bullet-point3': f"Weight: {product['weight']}",
                'bullet-point4': "",
                'bullet-point5': "",
                'main-image-url': product['main_image'],
                'other-image-url1': product['other_images'][0] if len(product['other_images']) > 0 else "",
                'other-image-url2': product['other_images'][1] if len(product['other_images']) > 1 else "",
                'other-image-url3': product['other_images'][2] if len(product['other_images']) > 2 else "",
                'other-image-url4': product['other_images'][3] if len(product['other_images']) > 3 else "",
                'item-price': product['price'].replace('€', '').replace('$', '').strip(),
                'quantity': '0' if product['stock_status'] != "Available" else '10',
                'condition-type': 'New',
                'item-weight': product['weight'].split()[0] if product['weight'] else "",
                'item-weight-unit-of-measure': 'GR',  # Grams
                'material-type': product['materials']
            }
            amazon_data.append(amazon_item)
        
        return pd.DataFrame(amazon_data, columns=self.config.AMAZON_FEED_COLUMNS)
    
    def generate_feeds(self):
        """Generate Amazon feed files"""
        # Create available products feed
        available_df = self.map_to_amazon_feed(self.products)
        available_path = os.path.join(self.config.OUTPUT_DIR, self.config.INVENTORY_FILE)
        available_df.to_excel(available_path, index=False)
        logger.info(f"Generated available products feed: {available_path}")
        
        # Create unavailable products feed
        unavailable_df = self.map_to_amazon_feed(self.unavailable_products)
        unavailable_path = os.path.join(self.config.OUTPUT_DIR, self.config.OUTOFSTOCK_FILE)
        unavailable_df.to_excel(unavailable_path, index=False)
        logger.info(f"Generated unavailable products feed: {unavailable_path}")
        
        return available_path, unavailable_path


def main():
    """Main function to run the jewelry scraper"""
    start_time = time.time()
    logger.info("Starting jewelry catalog scraper")
    
    scraper = JewelryScraper()
    scraper.scrape_all_products()
    available_path, unavailable_path = scraper.generate_feeds()
    
    # Summary
    elapsed_time = time.time() - start_time
    logger.info(f"Scraping completed in {elapsed_time:.2f} seconds")
    logger.info(f"Found {len(scraper.products)} available products")
    logger.info(f"Found {len(scraper.unavailable_products)} unavailable products")
    logger.info(f"Available products saved to: {available_path}")
    logger.info(f"Unavailable products saved to: {unavailable_path}")


if __name__ == "__main__":
    main()