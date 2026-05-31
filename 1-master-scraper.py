"""
Master Scraper Orchestrator
Executes all pharmacy scrapers in parallel using multiprocessing.
"""
from multiprocessing import Process
from scrapers.drogal.drogal_scraper import main as run_drogal_scraper
from scrapers.drogaven.drogaven_scraper import main as run_drogaven_scraper
from scrapers.drogaraia.drogaraia_scraper import main as run_drogaraia_scraper

if __name__ == "__main__":

    # Create a process for each imported scraper function
    drogal_process = Process(target=run_drogal_scraper)
    drogaven_process = Process(target=run_drogaven_scraper)
    drogaraia_process = Process(target=run_drogaraia_scraper)

    print("\n[STEP 1] Starting all parallel scrapers...")
    
    # Start all processes
    drogal_process.start()
    drogaven_process.start()
    drogaraia_process.start()


    # Wait for all processes to complete
    drogal_process.join()
    drogaven_process.join()
    drogaraia_process.join()

    print("\n[SUCCESS] All scrapers have finished. Raw data is ready in the 'output' folder.")
    print("Next Step: Run '2-concorrentes.py' to consolidate this data.")
