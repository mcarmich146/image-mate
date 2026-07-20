#!/usr/bin/env python3
"""
QGIS Plugin Deployment Script
Deploys the image_mate_qgis_plugin to the QGIS plugins folder
"""

import os
import shutil
import sys
import time
from pathlib import Path


def clean_pycache(directory):
    """Remove __pycache__ directories and .pyc files."""
    count = 0
    for root, dirs, files in os.walk(directory):
        # Remove __pycache__ directories
        for dir_name in list(dirs):
            if dir_name == '__pycache__':
                pycache_path = Path(root) / dir_name
                try:
                    shutil.rmtree(pycache_path)
                    count += 1
                except Exception as e:
                    print(f"Warning: Could not remove {pycache_path}: {e}")
        
        # Remove .pyc files
        for file_name in files:
            if file_name.endswith('.pyc'):
                pyc_path = Path(root) / file_name
                try:
                    pyc_path.unlink()
                    count += 1
                except Exception as e:
                    print(f"Warning: Could not remove {pyc_path}: {e}")
    return count


def copy_ignore(directory, contents):
    """Ignore function for shutil.copytree to skip cache files."""
    ignored = []
    for item in contents:
        if item == '__pycache__' or item.endswith('.pyc') or item.endswith('.pyo'):
            ignored.append(item)
    return ignored


def force_remove_dir(directory, max_retries=3):
    """Try to remove directory with retries for locked files."""
    for attempt in range(max_retries):
        try:
            if directory.exists():
                shutil.rmtree(directory)
            return True
        except PermissionError as e:
            if attempt < max_retries - 1:
                print(f"  Retry {attempt + 1}/{max_retries - 1}: File locked, waiting...")
                time.sleep(0.5)
            else:
                print(f"  ERROR: Could not remove directory after {max_retries} attempts")
                print(f"  {e}")
                print(f"  Please close QGIS and try again, or manually delete: {directory}")
                return False
        except Exception as e:
            print(f"  ERROR: {e}")
            return False
    return False


def main():
    print("=== QGIS Plugin Deployment ===")
    print()
    
    # Source directory (the plugin to deploy)
    script_dir = Path(__file__).parent
    source_dir = script_dir / "image_mate_qgis_plugin"
    
    # Target directory (QGIS plugins folder)
    appdata = Path(os.environ.get('APPDATA', ''))
    target_base = appdata / "QGIS" / "QGIS3" / "profiles" / "default" / "python" / "plugins"
    target_dir = target_base / "image_mate_qgis_plugin"
    
    print(f"Source: {source_dir}")
    print(f"Target: {target_dir}")
    print()
    
    # Check if source directory exists
    if not source_dir.exists():
        print(f"ERROR: Source directory not found: {source_dir}")
        sys.exit(1)
    
    # Clean up source __pycache__ before copying
    print("Cleaning source __pycache__ directories...")
    cleaned_count = clean_pycache(source_dir)
    if cleaned_count > 0:
        print(f"  Removed {cleaned_count} cache files/directories")
    
    # Create target base directory if it doesn't exist
    if not target_base.exists():
        print(f"WARNING: QGIS plugins directory not found: {target_base}")
        print("Creating directory...")
        target_base.mkdir(parents=True, exist_ok=True)
    
    # Remove existing plugin installation if it exists
    if target_dir.exists():
        print("Removing existing plugin installation...")
        if not force_remove_dir(target_dir):
            print()
            print("DEPLOYMENT FAILED: Could not remove existing plugin")
            print("Please close QGIS and try again")
            sys.exit(1)
        print("  Removed successfully")
    
    # Copy plugin to QGIS plugins directory
    print("Copying plugin files...")
    try:
        shutil.copytree(source_dir, target_dir, ignore=copy_ignore)
        print("  Copied successfully")
    except Exception as e:
        print(f"  ERROR: Failed to copy plugin files: {e}")
        sys.exit(1)
    
    # Verify deployment
    print("Verifying deployment...")
    key_files = ['__init__.py', 'plugin.py', 'metadata.txt']
    missing_files = []
    for key_file in key_files:
        if not (target_dir / key_file).exists():
            missing_files.append(key_file)
    
    if missing_files:
        print(f"  WARNING: Missing files: {', '.join(missing_files)}")
    else:
        print("  All key files present")
    
    # Count deployed files
    file_count = sum(1 for _ in target_dir.rglob('*.py'))
    print(f"  Deployed {file_count} Python files")
    
    print()
    print("=== Deployment Complete ===")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("Next steps:")
    print("1. If QGIS is running, restart it to load the updated plugin")
    print("2. Or use Plugin Manager > 'Reload plugin: image_mate_qgis_plugin' if you have Plugin Reloader installed")
    print("3. Enable the plugin in: Plugins > Manage and Install Plugins")
    print()


if __name__ == "__main__":
    main()
