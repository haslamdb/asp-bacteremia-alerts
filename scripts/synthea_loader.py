#!/usr/bin/env python3
"""Load Synthea-generated FHIR bundles into HAPI FHIR server.

Synthea generates synthetic patient data in FHIR format. This script
loads those bundles into your local HAPI FHIR server for testing.

Usage:
    # Load all bundles from Synthea output directory
    python synthea_loader.py /path/to/synthea/output/fhir

    # Load specific bundle files
    python synthea_loader.py patient1.json patient2.json

    # Specify custom FHIR server
    python synthea_loader.py --fhir-url http://localhost:8081/fhir /path/to/bundles

Synthea Setup:
    1. Download from https://github.com/synthetichealth/synthea
    2. Run: java -jar synthea-with-dependencies.jar -p 20 Ohio
    3. Find bundles in: output/fhir/

Pediatric-specific generation:
    java -jar synthea-with-dependencies.jar -p 50 --exporter.years_of_history 18 Ohio
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests


def load_bundle(bundle_path: Path, fhir_base_url: str) -> tuple[int, int]:
    """Load a FHIR bundle into the server.

    Args:
        bundle_path: Path to FHIR bundle JSON file
        fhir_base_url: Base URL of FHIR server

    Returns:
        Tuple of (resources_loaded, resources_failed)
    """
    with open(bundle_path) as f:
        bundle = json.load(f)

    if bundle.get("resourceType") != "Bundle":
        print(f"  Skipping {bundle_path.name}: not a Bundle")
        return 0, 0

    loaded = 0
    failed = 0

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")

        if not resource_type:
            continue

        # Use PUT to create/update with specific ID
        url = f"{fhir_base_url}/{resource_type}/{resource_id}"

        try:
            response = requests.put(
                url,
                json=resource,
                headers={
                    "Content-Type": "application/fhir+json",
                    "Accept": "application/fhir+json",
                },
            )
            response.raise_for_status()
            loaded += 1
        except requests.HTTPError as e:
            print(f"  Failed to load {resource_type}/{resource_id}: {e}")
            failed += 1

    return loaded, failed


def load_directory(dir_path: Path, fhir_base_url: str) -> tuple[int, int, int]:
    """Load all FHIR bundles from a directory.

    Args:
        dir_path: Directory containing FHIR bundle JSON files
        fhir_base_url: Base URL of FHIR server

    Returns:
        Tuple of (files_processed, resources_loaded, resources_failed)
    """
    json_files = list(dir_path.glob("*.json"))
    print(f"Found {len(json_files)} JSON files in {dir_path}")

    total_loaded = 0
    total_failed = 0
    files_processed = 0

    for json_file in json_files:
        print(f"Loading {json_file.name}...")
        loaded, failed = load_bundle(json_file, fhir_base_url)

        if loaded > 0 or failed > 0:
            files_processed += 1
            total_loaded += loaded
            total_failed += failed
            print(f"  Loaded {loaded} resources, {failed} failed")

    return files_processed, total_loaded, total_failed


def main():
    parser = argparse.ArgumentParser(
        description="Load Synthea FHIR bundles into HAPI FHIR server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Path(s) to FHIR bundle files or directories",
    )
    parser.add_argument(
        "--fhir-url",
        default="http://localhost:8081/fhir",
        help="FHIR server base URL (default: http://localhost:8081/fhir)",
    )

    args = parser.parse_args()

    # Check FHIR server is accessible
    try:
        response = requests.get(f"{args.fhir_url}/metadata")
        response.raise_for_status()
        print(f"Connected to FHIR server at {args.fhir_url}")
    except Exception as e:
        print(f"Error: Cannot connect to FHIR server at {args.fhir_url}")
        print(f"  {e}")
        sys.exit(1)

    total_files = 0
    total_loaded = 0
    total_failed = 0

    for path_str in args.paths:
        path = Path(path_str)

        if not path.exists():
            print(f"Warning: {path} does not exist, skipping")
            continue

        if path.is_dir():
            files, loaded, failed = load_directory(path, args.fhir_url)
            total_files += files
            total_loaded += loaded
            total_failed += failed
        else:
            print(f"Loading {path.name}...")
            loaded, failed = load_bundle(path, args.fhir_url)
            if loaded > 0 or failed > 0:
                total_files += 1
                total_loaded += loaded
                total_failed += failed
                print(f"  Loaded {loaded} resources, {failed} failed")

    print()
    print(f"Summary: Processed {total_files} files")
    print(f"  Resources loaded: {total_loaded}")
    print(f"  Resources failed: {total_failed}")


if __name__ == "__main__":
    main()
