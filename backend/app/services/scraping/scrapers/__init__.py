"""
Scraper registry — exports all site-specific scraper classes.
"""

from app.services.scraping.scrapers.carmax import CarMaxScraper
from app.services.scraping.scrapers.autotrader import AutotraderScraper
from app.services.scraping.scrapers.cargurus import CarGurusScraper

ALL_SCRAPERS = [CarMaxScraper, AutotraderScraper, CarGurusScraper]

__all__ = [
    "CarMaxScraper",
    "AutotraderScraper",
    "CarGurusScraper",
    "ALL_SCRAPERS",
]
