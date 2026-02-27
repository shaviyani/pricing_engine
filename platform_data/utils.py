"""
Shared utilities for platform_data.

Single source of truth for country name normalization used by both
MoT parser (PDF extraction) and guest-country matching (PMS data → MoT).
"""

import re

# ---------------------------------------------------------------------------
# Country normalization — single canonical map
# ---------------------------------------------------------------------------
# Keys are lowercase.  Values are the canonical name stored in MoT data.
COUNTRY_NORMALIZATION_MAP = {
    # Russia
    'russian federation': 'Russia',
    'russian': 'Russia',
    # United Kingdom
    'uk': 'United Kingdom',
    'u.k': 'United Kingdom',
    'u.k.': 'United Kingdom',
    'great britain': 'United Kingdom',
    'england': 'United Kingdom',
    'britain': 'United Kingdom',
    # United States
    'usa': 'United States',
    'u.s.a': 'United States',
    'u.s.a.': 'United States',
    'united states of america': 'United States',
    'america': 'United States',
    # UAE
    'uae': 'United Arab Emirates',
    'u.a.e': 'United Arab Emirates',
    'u.a.e.': 'United Arab Emirates',
    # South Korea
    'korea': 'South Korea',
    'republic of korea': 'South Korea',
    'south korea': 'South Korea',
    'korean': 'South Korea',
    # China
    'prc': 'China',
    "people's republic of china": 'China',
    'chinese': 'China',
    # Germany
    'deutsch': 'Germany',
    'deutschland': 'Germany',
    # Italy
    'italian': 'Italy',
    'italia': 'Italy',
    # France
    'french': 'France',
    'française': 'France',
    # Netherlands
    'holland': 'Netherlands',
    'the netherlands': 'Netherlands',
    'netherlands / holland': 'Netherlands',
    # Czech Republic
    'czech': 'Czech Republic',
    'czechia': 'Czech Republic',
    # Turkey
    'türkiye': 'Turkey',
    'turkiye': 'Turkey',
    # Vietnam
    'viet nam': 'Vietnam',
    # North Macedonia
    'republic of north macedonia': 'North Macedonia',
    'north macedonia': 'North Macedonia',
    # Saudi Arabia
    'saudi': 'Saudi Arabia',
    'ksa': 'Saudi Arabia',
    # Sri Lanka
    'sri lankan': 'Sri Lanka',
    # India
    'indian': 'India',
    # Maldives
    'maldives': 'Maldives',
    'maldivian': 'Maldives',
}


def normalize_country(name):
    """Normalize a country name to MoT canonical form.

    Handles:
    - PMS guest country variants ("Russian Federation", "UK", "USA")
    - MoT PDF formatting artefacts (trailing *, mixed case)
    - Case insensitive lookup

    Returns the canonical name or the original (title-cased if all
    upper/lower) when no mapping exists.
    """
    if not name:
        return ''
    clean = name.strip()
    clean = re.sub(r'\s*\*\s*$', '', clean)  # Remove trailing * from MoT PDFs
    lower = clean.lower()

    mapped = COUNTRY_NORMALIZATION_MAP.get(lower)
    if mapped:
        return mapped

    # Title-case purely upper/lower input; leave mixed case as-is
    if clean == clean.upper() or clean == clean.lower():
        return clean.title()
    return clean
