import streamlit as st
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dataclasses import dataclass, asdict, field
import pandas as pd
import os
import csv
import random
import time

# List of business categories
business_types = [
    "Real Estate companies", "Charity/Non-Profits", "Portfolio sites for Instagram artists",
    "Local Restaurant chains", "Personal Injury Law Firms", "Independent insurance sites",
    "Landscaping/Fertilizer", "Painting", "Power Washing", "Car Wash", "Axe Throwing", "Gun Ranges/Stores",
    "Currency Exchanges/Check Cashing", "Construction Materials Companies", "Gyms", "Salons with multiple locations",
    "Eyebrow Microblading", "Estheticians", "Orthodontists", "Used Car dealerships", "Clothing Brand", "Cut & Sew", "Embroidery"
]

@dataclass
class Business:
    """Holds business data"""
    name: str = None
    address: str = "No Address"
    website: str = "No Website"
    phone_number: str = "No Phone"
    reviews_count: int = 0
    reviews_average: float = 0.0
    latitude: float = None
    longitude: float = None

@dataclass
class BusinessList:
    """Holds list of Business objects and saves to both Excel and CSV."""
    business_list: list = field(default_factory=list)
    save_at: str = 'output'
    seen_businesses: set = field(default_factory=set)

    def dataframe(self):
        """Transform business_list to a pandas dataframe."""
        return pd.json_normalize(
            (asdict(business) for business in self.business_list), sep="_"
        )

    def save_to_csv(self, filename, append=True):
        """Saves pandas dataframe to a single centralized CSV file with headers."""
        if not os.path.exists(self.save_at):
            os.makedirs(self.save_at)
        file_path = f"{self.save_at}/{filename}.csv"
        mode = 'a' if append else 'w'
        if append and os.path.exists(file_path):
            self.dataframe().to_csv(file_path, mode=mode, index=False, header=False)
        else:
            self.dataframe().to_csv(file_path, mode=mode, index=False, header=True)

    def add_business(self, business):
        """Add a business to the list if it's not a duplicate."""
        unique_key = (business.name, business.address, business.phone_number)
        if unique_key not in self.seen_businesses:
            self.seen_businesses.add(unique_key)
            self.business_list.append(business)
            return True
        return False

def extract_coordinates_from_url(url: str) -> tuple:
    """Helper function to extract coordinates from URL."""
    try:
        coordinates = url.split('/@')[-1].split('/')[0]
        return float(coordinates.split(',')[0]), float(coordinates.split(',')[1])
    except (IndexError, ValueError):
        return None, None

def clean_business_name(name: str) -> str:
    """Remove '· Visited link' from the business name."""
    return name.replace(" · Visited link", "").strip()

def get_cities_and_states_from_csv(file):
    """Read cities and states from uploaded CSV file."""
    df = pd.read_csv(file)
    return list(zip(df['city'], df['state_id']))

def scrape_businesses(selected_business_types, num_listings, headless, cities_states, progress_bar, status_text):
    """Main scraping function."""
    business_list = BusinessList()
    centralized_filename = "Scraped_results"
    total_listings = len(selected_business_types) * num_listings
    progress = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        for selected_business_type in selected_business_types:
            st.write(f"Scraping for: {selected_business_type}")
            listings_scraped = 0
            cities_states_copy = cities_states.copy()

            while listings_scraped < num_listings and cities_states_copy:
                selected_city, selected_state = random.choice(cities_states_copy)
                cities_states_copy.remove((selected_city, selected_state))
                search_for = f"{selected_business_type} in {selected_city}, {selected_state}"
                status_text.text(f"Searching: {search_for}")

                try:
                    page.goto("https://www.google.com/maps", timeout=30000)
                    page.wait_for_selector('//input[@id="searchboxinput"]', timeout=10000)
                    page.locator('//input[@id="searchboxinput"]').fill(search_for)
                    page.keyboard.press("Enter")
                    page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]', timeout=7000)
                except PlaywrightTimeoutError:
                    status_text.text(f"Timeout for {search_for}. Skipping...")
                    continue

                current_count = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').count()
                if current_count == 0:
                    status_text.text(f"No results for {search_for}. Moving to next city.")
                    continue

                while listings_scraped < num_listings:
                    listings = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').all()
                    for listing in listings:
                        if listings_scraped >= num_listings:
                            break

                        listing.click()
                        page.wait_for_timeout(2000)

                        business = Business()
                        business.name = clean_business_name(listing.get_attribute('aria-label') or "Unknown")
                        business.address = page.locator('xpath=//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]').first.inner_text() or "No Address"
                        business.website = page.locator('xpath=//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]').first.inner_text() or "No Website"
                        business.phone_number = page.locator('xpath=//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]').first.inner_text() or "No Phone"

                        reviews_avg = page.locator('div[role="main"]//span[@role="img"]').first.get_attribute('aria-label')
                        if reviews_avg:
                            match = re.search(r'(\d+\.\d+|\d+)', reviews_avg.replace(',', '.'))
                            business.reviews_average = float(match.group(1)) if match else 0.0

                        reviews_count = page.locator('div[role="main"]//button[./span[contains(text(), "reviews")]]/span').first.inner_text()
                        if reviews_count:
                            match = re.search(r'(\d+)', reviews_count.replace(',', ''))
                            business.reviews_count = int(match.group(1)) if match else 0

                        business.latitude, business.longitude = extract_coordinates_from_url(page.url)

                        if business_list.add_business(business):
                            listings_scraped += 1
                            progress += 1
                            progress_bar.progress(progress / total_listings)
                            status_text.text(f"Scraped {progress} of {total_listings}: {business.name}")

                    page.mouse.wheel(0, 5000)
                    page.wait_for_timeout(3000)
                    if page.locator("text=You've reached the end of the list").is_visible():
                        break

            if business_list.business_list:
                business_list.save_to_csv(centralized_filename, append=True)
                business_list.business_list.clear()

        browser.close()
    return business_list.dataframe()

# Streamlit UI
def main():
    st.title("Google Maps Business Scraper")
    st.write("Select business categories and configure scraping settings.")

    # Business category selection
    selected_business_types = st.multiselect("Select Business Categories", business_types, default=[business_types[0]])

    # Headless mode
    headless = st.checkbox("Run in Headless Mode", value=True)

    # Number of listings
    num_listings = st.number_input("Number of Listings per Category", min_value=1, value=10, step=1)

    # Upload uscities.csv
    uploaded_file = st.file_uploader("Upload uscities.csv", type=["csv"])
    
    if uploaded_file:
        cities_states = get_cities_and_states_from_csv(uploaded_file)
        st.write(f"Loaded {len(cities_states)} cities from uscities.csv")

        # Scrape button
        if st.button("Start Scraping"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            df = scrape_businesses(selected_business_types, num_listings, headless, cities_states, progress_bar, status_text)
            
            # Display results
            st.write("### Scraped Data")
            st.dataframe(df)

            # Download button
            csv_file = df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv_file,
                file_name="scraped_results.csv",
                mime="text/csv"
            )
    else:
        st.warning("Please upload uscities.csv to proceed.")

if __name__ == "__main__":
    main()
