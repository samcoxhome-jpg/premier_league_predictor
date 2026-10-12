#Clears Streamlit's saved cache and the __pycache__ folders so old results dont show up
#Stop the app first, run this, then start it again
#Run with: python clean_restart.py

import shutil
from pathlib import Path


def clear_streamlit_disk_cache():
    try:
        from streamlit.file_util import get_streamlit_file_path
        cache_dir = Path(get_streamlit_file_path("cache"))
    except Exception:
        #Backup in case Streamlit changes this in a newer version
        cache_dir = Path.home() / ".streamlit" / "cache"

    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        print(f"Cleared Streamlit disk cache: {cache_dir}")
    else:
        print(f"No Streamlit disk cache found at {cache_dir} (nothing to clear)")


def clear_pycache(root: Path):
    cleared = 0
    for pycache_dir in root.rglob("__pycache__"):
        shutil.rmtree(pycache_dir)
        cleared += 1
    print(f"Cleared {cleared} __pycache__ folder(s) under {root}")


def main():
    project_root = Path(__file__).parent

    print("Clearing caches...\n")
    clear_streamlit_disk_cache()
    clear_pycache(project_root)

    print("\nDone.")
    print("Restart the app with run.bat")


if __name__ == "__main__":
    main()
