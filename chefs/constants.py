"""
MEHKO/IFSI compliance constants for California.

Sources:
- AB 626 (2018), AB 1325 (2023)
- COOK Alliance FAQ: https://www.cookalliance.org/frequently-asked-questions
- mehko.org: https://mehko.org/list-california-counties-mehko-accepting-applications/

Last verified: February 2026. County opt-in status changes — verify before onboarding.
"""

# Counties and city jurisdictions that have opted in to MEHKO permitting.
# Each entry is the jurisdiction name as it should appear in Chef.county.
MEHKO_APPROVED_COUNTIES = [
    "Alameda",
    "Amador",
    "Contra Costa",
    "Imperial",
    "Lake",
    "Los Angeles",
    "Monterey",
    "Riverside",
    "San Benito",
    "San Diego",
    "San Mateo",
    "Santa Barbara",
    "Santa Clara",
    "Santa Cruz",
    "Sierra",
    "Solano",
    "Sonoma",
    # City jurisdictions with their own health departments
    "City of Berkeley",
]

# Meal caps per §113825 (as amended by AB 1325)
MEHKO_DAILY_MEAL_CAP = 30
MEHKO_WEEKLY_MEAL_CAP = 90

# Annual revenue cap per §113825 (as amended by AB 1325)
# Note: statute says "inflation-adjusted" — update periodically
MEHKO_ANNUAL_REVENUE_CAP = 100_000  # dollars

# County → local enforcement agency contact info
# Used for complaint routing and disclosure pages
COUNTY_ENFORCEMENT_AGENCIES = {
    "Alameda": {
        "name": "Alameda County Department of Environmental Health",
        "url": "https://deh.acgov.org/operations/home-based-food-business.page",
    },
    "Amador": {
        "name": "Amador County Environmental Health",
        "url": "https://www.amadorgov.org/services/environmental-health",
    },
    "Contra Costa": {
        "name": "Contra Costa County Environmental Health",
        "url": "https://cchealth.org/eh/",
    },
    "Imperial": {
        "name": "Imperial County Environmental Health Services",
        "url": "https://www.imperialcounty.org/publichealth/environmental-health/",
    },
    "Lake": {
        "name": "Lake County Environmental Health",
        "url": "https://www.lakecountyca.gov/Government/Directory/EnvironmentalHealth.htm",
    },
    "Los Angeles": {
        "name": "LA County Department of Public Health, Environmental Health",
        "url": "http://publichealth.lacounty.gov/eh/business/microenterprise-home-kitchen-operation.htm",
    },
    "Monterey": {
        "name": "Monterey County Environmental Health Bureau",
        "url": "https://www.co.monterey.ca.us/government/departments-a-h/health/environmental-health",
    },
    "Riverside": {
        "name": "Riverside County Department of Environmental Health",
        "url": "https://www.rivcoeh.org/",
    },
    "San Benito": {
        "name": "San Benito County Environmental Health",
        "url": "https://hhsa.cosb.us/environmental-health/",
    },
    "San Diego": {
        "name": "San Diego County Department of Environmental Health",
        "url": "https://www.sandiegocounty.gov/deh/",
    },
    "San Mateo": {
        "name": "San Mateo County Environmental Health Services",
        "url": "https://www.smchealth.org/microkitchens-mehko",
    },
    "Santa Barbara": {
        "name": "Santa Barbara County Environmental Health Services",
        "url": "https://www.countyofsb.org/phd/environmentalhealth.sbc",
    },
    "Santa Clara": {
        "name": "Santa Clara County Department of Environmental Health",
        "url": "https://www.sccgov.org/sites/deh/Pages/deh.aspx",
    },
    "Santa Cruz": {
        "name": "Santa Cruz County Environmental Health",
        "url": "https://www.santacruzhealth.org/HSADivisions/EnvironmentalHealth.aspx",
    },
    "Sierra": {
        "name": "Sierra County Environmental Health",
        "url": "https://www.sierracounty.ca.gov/",
    },
    "Solano": {
        "name": "Solano County Department of Resource Management",
        "url": "https://www.solanocounty.com/depts/rm/environmental_health/default.asp",
    },
    "Sonoma": {
        "name": "Sonoma County Permit & Resource Management Department",
        "url": "https://sonomacounty.ca.gov/PRMD/Regulations/Environmental-Health-and-Safety/",
    },
    "City of Berkeley": {
        "name": "City of Berkeley Environmental Health",
        "url": "https://www.cityofberkeley.info/Health_Human_Services/Environmental_Health/",
    },
}
