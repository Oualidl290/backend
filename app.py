# Placeholder content for app.py// app.py - Flask Backend
import os
import time
import json
import threading
import pandas as pd
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# Import your scraper code
from jewelry_scraper import JewelryScraper, JewelryScraperConfig

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variables to track scraper state
scraper_status = {
    "status": "Idle",
    "progress": 0,
    "pages_crawled": 0,
    "total_pages": 0,
    "products_processed": 0,
    "total_products": 0,
    "available_products": 0,
    "unavailable_products": 0,
    "time_elapsed": "0:00:00",
    "feed_status": "Pending",
    "start_time": None,
    "job_id": None
}

# Job history
job_history = []

# Lock for thread-safe operations
status_lock = threading.Lock()

# Directory for data storage
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# Configuration storage
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

def load_config():
    """Load configuration from file"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        "base_url": "",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "request_delay": 2,
        "max_retries": 3,
        "categories": ["/necklaces", "/earrings", "/rings", "/bracelets", "/pendants"]
    }

def save_config(config):
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

def format_time_elapsed(seconds):
    """Format seconds into HH:MM:SS"""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"

def update_scraper_status(update_dict):
    """Thread-safe update of scraper status"""
    with status_lock:
        scraper_status.update(update_dict)

def scraper_thread(config):
    """Thread function to run the scraper"""
    job_id = f"job-{datetime.now().strftime('%Y%m%d%H')}-{len(job_history) + 1}"
    start_time = time.time()
    
    # Update status to Running
    update_scraper_status({
        "status": "Running",
        "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "job_id": job_id,
        "progress": 0,
        "feed_status": "Processing"
    })
    
    # Configure the scraper
    scraper_config = JewelryScraperConfig()
    scraper_config.BASE_URL = config["base_url"]
    scraper_config.HEADERS["User-Agent"] = config["user_agent"]
    scraper_config.CATEGORY_URLS = config["categories"]
    
    # Create scraper instance
    scraper = JewelryScraper(scraper_config)
    
    # Track progress
    total_categories = len(config["categories"])
    processed_categories = 0
    
    issues = {
        "errors": 0,
        "warnings": 0
    }
    
    try:
        # For each category
        all_product_links = []
        update_scraper_status({"total_pages": 0})
        
        for category_url in scraper_config.CATEGORY_URLS:
            # Update status for category
            update_scraper_status({
                "status": f"Scraping category: {category_url}"
            })
            
            # Scrape category
            try:
                category_links = scraper.scrape_category(category_url)
                all_product_links.extend(category_links)
                processed_categories += 1
                
                # Update progress
                progress = int((processed_categories / total_categories) * 30)  # 30% of progress for categories
                update_scraper_status({
                    "progress": progress,
                    "pages_crawled": scraper_status["pages_crawled"],
                    "total_pages": scraper_status["total_pages"] 
                })
                
            except Exception as e:
                issues["errors"] += 1
                print(f"Error scraping category {category_url}: {str(e)}")
        
        # Remove duplicates
        unique_links = list(set(all_product_links))
        update_scraper_status({
            "status": "Processing products",
            "total_products": len(unique_links)
        })
        
        # Process each product
        for i, link in enumerate(unique_links):
            try:
                # Update status
                update_scraper_status({
                    "status": f"Processing product {i+1}/{len(unique_links)}",
                    "products_processed": i + 1
                })
                
                # Calculate progress (30-90% range for products)
                product_progress = int(30 + ((i + 1) / len(unique_links) * 60))
                update_scraper_status({"progress": product_progress})
                
                # Process the product
                html = scraper.get_page(link)
                if html:
                    product = scraper.parse_product_page(html, link)
                    if product:
                        if product['stock_status'] in ["Out of Stock", "In Production", "Removed"]:
                            scraper.unavailable_products.append(product)
                            update_scraper_status({"unavailable_products": len(scraper.unavailable_products)})
                        else:
                            scraper.products.append(product)
                            update_scraper_status({"available_products": len(scraper.products)})
                
                # Update elapsed time
                elapsed = time.time() - start_time
                update_scraper_status({"time_elapsed": format_time_elapsed(elapsed)})
                
                # Pause briefly
                if i % 10 == 0:
                    time.sleep(float(config["request_delay"]))
                else:
                    time.sleep(0.5)
                    
            except Exception as e:
                issues["warnings"] += 1
                print(f"Error processing product {link}: {str(e)}")
        
        # Generate feeds
        update_scraper_status({
            "status": "Generating feeds",
            "progress": 90
        })
        
        try:
            available_path, unavailable_path = scraper.generate_feeds()
            update_scraper_status({
                "feed_status": "Completed"
            })
        except Exception as e:
            issues["errors"] += 1
            update_scraper_status({
                "feed_status": "Failed"
            })
            print(f"Error generating feeds: {str(e)}")
        
        # Completed
        elapsed_time = time.time() - start_time
        formatted_time = format_time_elapsed(elapsed_time)
        
        # Update final status
        update_scraper_status({
            "status": "Idle",
            "progress": 100,
            "time_elapsed": formatted_time
        })
        
        # Add to job history
        duration = formatted_time
        products_count = f"{len(scraper.products)} / {len(unique_links)}"
        status = "Completed"
        
        with status_lock:
            job_history.append({
                "job_id": job_id,
                "start_time": scraper_status["start_time"],
                "duration": duration,
                "status": status,
                "products": products_count,
                "issues": f"{issues['errors']} errors, {issues['warnings']} warnings" if issues['errors'] or issues['warnings'] else "None"
            })
            
    except Exception as e:
        # Handle any unexpected errors
        print(f"Unexpected error: {str(e)}")
        update_scraper_status({
            "status": "Idle",
            "progress": 0,
            "feed_status": "Failed"
        })
        
        # Add failed job to history
        with status_lock:
            job_history.append({
                "job_id": job_id,
                "start_time": scraper_status["start_time"],
                "duration": "-",
                "status": "Failed",
                "products": f"0 / {len(all_product_links)}",
                "issues": f"1 errors, 0 warnings"
            })

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get current scraper status"""
    with status_lock:
        return jsonify(scraper_status)

@app.route('/api/start', methods=['POST'])
def start_scraper():
    """Start the scraper process"""
    if scraper_status["status"] != "Idle":
        return jsonify({"error": "Scraper is already running"}), 400
    
    # Load configuration
    config = load_config()
    
    # Start scraper in a separate thread
    thread = threading.Thread(target=scraper_thread, args=(config,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Scraper started"})

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    """Get or update configuration"""
    if request.method == 'GET':
        return jsonify(load_config())
    else:
        config = request.json
        save_config(config)
        return jsonify({"message": "Configuration saved"})

@app.route('/api/test-connection', methods=['POST'])
def test_connection():
    """Test connection to supplier website"""
    config = request.json
    base_url = config.get('base_url')
    
    if not base_url:
        return jsonify({"success": False, "message": "Base URL is required"}), 400
    
    try:
        import requests
        response = requests.get(
            base_url, 
            headers={"User-Agent": config.get('user_agent', 'Mozilla/5.0')},
            timeout=10
        )
        response.raise_for_status()
        return jsonify({
            "success": True, 
            "message": f"Connection successful! Status code: {response.status_code}"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Connection failed: {str(e)}"
        }), 400

@app.route('/api/history', methods=['GET'])
def get_history():
    """Get job history"""
    return jsonify(job_history)

@app.route('/api/products', methods=['GET'])
def get_products():
    """Get product data"""
    status = request.args.get('status', 'available')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    
    # Get file path based on status
    file_path = os.path.join(DATA_DIR, 'full_inventory.xlsx' if status == 'available' else 'out_of_stock.xlsx')
    
    if not os.path.exists(file_path):
        return jsonify({"error": "No data available"}), 404
    
    try:
        # Read Excel file
        df = pd.read_excel(file_path)
        
        # Calculate pagination
        total_records = len(df)
        total_pages = (total_records + per_page - 1) // per_page
        
        # Get page data
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_records)
        page_data = df.iloc[start_idx:end_idx].to_dict('records')
        
        return jsonify({
            "data": page_data,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_records": total_records,
                "total_pages": total_pages
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/export/<file_type>', methods=['GET'])
def export_data(file_type):
    """Export data files"""
    if file_type == 'inventory':
        file_path = os.path.join(DATA_DIR, 'full_inventory.xlsx')
    elif file_type == 'outofstock':
        file_path = os.path.join(DATA_DIR, 'out_of_stock.xlsx')
    else:
        return jsonify({"error": "Invalid file type"}), 400
    
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    
    return send_file(file_path, as_attachment=True)

@app.route('/api/summary', methods=['GET'])
def get_summary():
    """Get job summary statistics"""
    inventory_file = os.path.join(DATA_DIR, 'full_inventory.xlsx')
    outofstock_file = os.path.join(DATA_DIR, 'out_of_stock.xlsx')
    
    available_count = 0
    unavailable_count = 0
    
    if os.path.exists(inventory_file):
        df = pd.read_excel(inventory_file)
        available_count = len(df)
    
    if os.path.exists(outofstock_file):
        df = pd.read_excel(outofstock_file)
        unavailable_count = len(df)
    
    # Get last run info from job history
    last_run = job_history[-1]["start_time"] if job_history else None
    
    return jsonify({
        "products_scraped": available_count + unavailable_count,
        "in_stock": available_count,
        "last_run": last_run,
        "success_rate": "98%" if job_history else "0%"
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)