#!/usr/bin/env python
"""Generate SPDX SBOM for FastAPI."""

import json
import subprocess
from datetime import datetime
from pathlib import Path


def get_installed_packages():
    """Get list of installed packages."""
    result = subprocess.run(
        ["pip", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def generate_spdx_sbom():
    """Generate SPDX format SBOM."""
    packages = get_installed_packages()

    spdx = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "FastAPI-SBOM",
        "documentNamespace": f"https://github.com/fastapi/fastapi/sbom-{datetime.now().isoformat()}",
        "creationInfo": {
            "created": datetime.now().isoformat(),
            "creators": ["Tool: FastAPI-SBOM-Generator"],
            "licenseListVersion": "3.21",
        },
        "packages": [],
    }

    # Add FastAPI itself
    spdx["packages"].append({
        "SPDXID": "SPDXRef-Package-FastAPI",
        "name": "FastAPI",
        "versionInfo": next(p["version"] for p in packages if p["name"] == "fastapi"),
        "downloadLocation": "https://github.com/fastapi/fastapi",
        "filesAnalyzed": False,
        "licenseConcluded": "MIT",
        "licenseDeclared": "MIT",
        "copyrightText": "Copyright (c) Sebastián Ramírez",
    })

    # Add all dependencies
    for pkg in packages:
        if pkg["name"] != "fastapi":
            spdx["packages"].append({
                "SPDXID": f"SPDXRef-Package-{pkg['name']}",
                "name": pkg["name"],
                "versionInfo": pkg["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
            })

    # Write SBOM
    output_path = Path("sbom.spdx")
    with open(output_path, "w") as f:
        json.dump(spdx, f, indent=2)

    print(f"✅ SPDX SBOM generated: {output_path}")
    print(f"   Total packages: {len(spdx['packages'])}")


if __name__ == "__main__":
    generate_spdx_sbom()
