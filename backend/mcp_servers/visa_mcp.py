"""
Visa & Travel Compliance MCP Server
Uses the LLM waterfall (Groq → Gemini → Anthropic → Template) to generate
accurate, personalised visa and entry requirement advice based on the
traveller's actual passport country and destination.

Also fetches live country data from REST Countries API to ground the LLM
with verified facts: country names, currencies, capital cities, regions.

Architecture:
  1. Fetch live country data → REST Countries (no key required)
  2. Build a grounded prompt with: passport, destination, duration,
     travel purpose, customer profile context
  3. Call LLM waterfall → structured JSON compliance report
  4. Cache per (passport × destination) for 24h
"""
import json
import logging
from .base_mcp    import BaseMCP
from .http_client import get

log = logging.getLogger(__name__)

REST_COUNTRIES_BASE = "https://restcountries.com/v3.1"

# Country ISO2 → full name mapping (local cache to reduce API calls)
COUNTRY_NAMES = {
    "GB":"United Kingdom","US":"United States","AU":"Australia","CA":"Canada",
    "IE":"Ireland","NZ":"New Zealand","IN":"India","CN":"China","PK":"Pakistan",
    "NG":"Nigeria","ZA":"South Africa","KE":"Kenya","GH":"Ghana",
    "DE":"Germany","FR":"France","IT":"Italy","ES":"Spain","PT":"Portugal",
    "NL":"Netherlands","BE":"Belgium","AT":"Austria","CH":"Switzerland",
    "GR":"Greece","PL":"Poland","SE":"Sweden","NO":"Norway","DK":"Denmark",
    "TR":"Turkey","AE":"United Arab Emirates","SA":"Saudi Arabia","QA":"Qatar",
    "SG":"Singapore","JP":"Japan","KR":"South Korea","TH":"Thailand",
    "MY":"Malaysia","ID":"Indonesia","PH":"Philippines","VN":"Vietnam",
    "MV":"Maldives","LK":"Sri Lanka","NP":"Nepal","BD":"Bangladesh",
    "BR":"Brazil","MX":"Mexico","AR":"Argentina","CO":"Colombia",
    "MA":"Morocco","EG":"Egypt","TN":"Tunisia","TZ":"Tanzania",
    "MU":"Mauritius","SC":"Seychelles","ET":"Ethiopia","RW":"Rwanda",
    # Destinations
    "PT":"Portugal","ES":"Spain","FR":"France","IT":"Italy","GR":"Greece",
    "HR":"Croatia","CY":"Cyprus","MT":"Malta","DXB":"United Arab Emirates",
    "DPS":"Indonesia (Bali)","MLE":"Maldives","BKK":"Thailand",
    "MRU":"Mauritius","SEZ":"Seychelles","CMN":"Morocco",
}

# IATA city code → ISO country code
IATA_TO_COUNTRY = {
    "LIS":"PT","OPO":"PT","FAO":"PT","BCN":"ES","MAD":"ES","PMI":"ES",
    "TFS":"ES","FCO":"IT","MXP":"IT","VCE":"IT","CDG":"FR","ORY":"FR",
    "AMS":"NL","BRU":"BE","VIE":"AT","ZRH":"CH","GVA":"CH","ATH":"GR",
    "SKG":"GR","RHO":"GR","LCA":"CY","DXB":"AE","AUH":"AE","DOH":"QA",
    "JFK":"US","LAX":"US","ORD":"US","MIA":"US","LHR":"GB","LGW":"GB",
    "SIN":"SG","NRT":"JP","KIX":"JP","BKK":"TH","HKT":"TH","DPS":"ID",
    "CGK":"ID","MLE":"MV","CMB":"LK","MRU":"MU","SEZ":"SC","NBO":"KE",
    "MBA":"KE","DAR":"TZ","CMN":"MA","TUN":"TN","CAI":"EG","ADD":"ET",
    "KGL":"RW","SYD":"AU","MEL":"AU","AKL":"NZ","YYZ":"CA","YVR":"CA",
    "GRU":"BR","BOG":"CO","CUN":"MX","HAN":"VN","SGN":"VN","KUL":"MY",
    "MNL":"PH","ICN":"KR","PEK":"CN","PVG":"CN","DEL":"IN","BOM":"IN",
    "MAA":"IN","HYD":"IN","CCU":"IN","KHI":"PK","LHE":"PK","ISB":"PK",
    "LOS":"NG","ACC":"GH","JNB":"ZA","CPT":"ZA","DUR":"ZA",
}

# Regional bloc membership (for quick Schengen/EU checks)
SCHENGEN = {"AT","BE","CZ","DK","EE","FI","FR","DE","GR","HU","IS","IT",
             "LV","LI","LT","LU","MT","NL","NO","PL","PT","SK","SI","ES",
             "SE","CH"}

SYSTEM_PROMPT = """You are VoyageAI's Visa & Travel Compliance AI — a specialist in international travel regulations.

Your job is to provide accurate, structured travel compliance advice based on:
- The traveller's passport/nationality
- The destination country
- Duration and purpose of travel
- Current entry requirements

CRITICAL RULES:
1. Only state requirements you are confident about for the given passport + destination combination
2. Always recommend verifying with the official embassy or FCDO (for UK) / State Dept (for US)
3. Include eVisa/ETA costs and application links where known
4. Flag any health requirements (vaccinations, health declarations)
5. Mention travel insurance requirements where applicable
6. Note any recent changes or special conditions (e.g., post-Brexit UK rules)

RESPONSE: Return ONLY valid JSON, no other text.

{
  "visa_required": true | false | "visa_on_arrival" | "eta_required" | "evisa_required" | "check_required",
  "entry_type": "visa_free" | "visa_on_arrival" | "evisa" | "eta" | "embassy_visa" | "unknown",
  "max_stay_days": integer or null,
  "cost": "Free" | "£25" | "$21" | etc. or null,
  "processing_time": "Instant" | "24-72 hours" | "5-10 working days" etc. or null,
  "apply_url": "URL" or null,
  "passport_validity": "minimum passport validity required e.g. 6 months beyond travel",
  "requirements": ["list", "of", "key", "requirements"],
  "health_requirements": ["any vaccinations or health certificates required"],
  "travel_warnings": ["any current warnings or advisories"],
  "currency_tip": "local currency name and practical tip",
  "emergency_contacts": {"embassy_in_destination": "phone or address if known"},
  "compliance_score": 0.0-1.0 (how confident you are in this information),
  "last_updated_note": "note about when rules were last updated or any uncertainty",
  "summary": "2-3 sentence plain English summary of what this traveller needs to do"
}"""


class VisaMCP(BaseMCP):
    """AI-powered visa and travel compliance checker."""

    def __init__(self):
        super().__init__(ttl=86400)   # cache 24h per passport+destination pair

    def _fetch(self, params: dict) -> dict:
        passport_code = params.get("passport_country", "GB").upper()[:2]
        dest_code     = params.get("destination_country", "PT").upper()

        # Resolve city code → country code if needed
        if len(dest_code) == 3:
            dest_code = IATA_TO_COUNTRY.get(dest_code, dest_code[:2])

        duration     = int(params.get("duration_days", 7))
        purpose      = params.get("purpose", "leisure")
        customer_name= params.get("customer_name", "")
        profile_info = params.get("profile", {})

        passport_name = COUNTRY_NAMES.get(passport_code, passport_code)
        dest_name     = COUNTRY_NAMES.get(dest_code, dest_code)

        # Fetch live country data from REST Countries to ground the LLM
        country_context = self._fetch_country_data(dest_code)

        # Build the grounded LLM prompt
        user_prompt = self._build_prompt(
            passport_code, passport_name,
            dest_code, dest_name,
            duration, purpose,
            country_context, profile_info
        )

        # Call LLM waterfall
        result = self._llm_compliance_check(user_prompt)

        # Enrich with always-correct data
        result = self._enrich(result, passport_code, dest_code,
                              dest_name, passport_name, duration)

        return {
            "data":       result,
            "passport":   passport_name,
            "destination":dest_name,
            "ai_powered": True,
        }

    def _fetch_country_data(self, dest_code: str) -> dict:
        """Fetch live country information from REST Countries API."""
        try:
            r = get(
                f"{REST_COUNTRIES_BASE}/alpha/{dest_code}",
                params={"fields": "name,capital,currencies,languages,region,subregion,"
                                  "flags,timezones,continents,tld,idd"},
                timeout=4,
            )
            if r.ok:
                d = r.json()
                if isinstance(d, list):
                    d = d[0]
                currencies = d.get("currencies", {})
                curr_info  = ""
                for code, info in currencies.items():
                    curr_info += f"{info.get('name',code)} ({code}, symbol: {info.get('symbol','')})"
                return {
                    "name":       d.get("name", {}).get("common", dest_code),
                    "capital":    (d.get("capital") or [dest_code])[0],
                    "region":     d.get("region",""),
                    "subregion":  d.get("subregion",""),
                    "currencies": curr_info,
                    "languages":  ", ".join(d.get("languages",{}).values()),
                    "timezones":  (d.get("timezones") or ["UTC"])[0],
                }
        except Exception as e:
            log.debug("REST Countries fetch error: %s", e)
        return {"name": COUNTRY_NAMES.get(dest_code, dest_code)}

    def _build_prompt(self, passport_code, passport_name,
                      dest_code, dest_name,
                      duration, purpose,
                      country_ctx, profile) -> str:
        """Build a rich, grounded prompt for the LLM."""

        # Schengen flag for extra context
        schengen_note = ""
        if dest_code in SCHENGEN and passport_code == "GB":
            schengen_note = ("Note: The UK left the EU/Schengen Area (Brexit). "
                             "UK passport holders are now subject to Schengen 90/180-day rule "
                             "and must use non-EU/EEA lanes at border control.")
        elif dest_code in SCHENGEN:
            schengen_note = f"{dest_name} is a Schengen Area member. Consider Schengen visa rules."

        # Profile context
        profile_lines = []
        if profile.get("travel_style"):
            profile_lines.append(f"Travel purpose: {profile['travel_style']}")
        if profile.get("adults_in_family"):
            profile_lines.append(f"Group: {profile.get('adults_in_family',1)} adults, {profile.get('children_in_family',0)} children")

        profile_text = "\n".join(profile_lines) if profile_lines else ""

        country_info = "\n".join(
            f"  {k}: {v}" for k, v in country_ctx.items() if v
        )

        return f"""Provide visa and travel compliance requirements for this specific traveller:

TRAVELLER DETAILS:
  Passport nationality: {passport_name} ({passport_code})
  Destination: {dest_name} ({dest_code})
  Length of stay: {duration} nights
  Travel purpose: {purpose}
  {profile_text}

DESTINATION FACTS (verified from REST Countries API):
{country_info}

ADDITIONAL CONTEXT:
{schengen_note}

Please provide comprehensive, accurate entry requirements for a {passport_name} passport holder
travelling to {dest_name} for {duration} nights for {purpose}.

Include:
1. Whether a visa/ETA/eVisa is required
2. Exact cost and where to apply (official government links only)
3. Processing time and validity
4. Passport validity requirements
5. Any health/vaccination requirements
6. Current travel advisories or restrictions
7. Local currency and practical tips
8. Emergency contact information

Return ONLY the JSON object as specified in the system prompt."""

    def _llm_compliance_check(self, user_prompt: str) -> dict:
        """Call the LLM waterfall and parse the JSON response."""
        try:
            from llm import get_waterfall
            waterfall = get_waterfall()
            resp      = waterfall.complete(
                system     = SYSTEM_PROMPT,
                user       = user_prompt,
                max_tokens = 1200,
                temperature= 0.05,   # very low — factual response needed
            )
            if resp.success:
                return json.loads(resp.text)
        except json.JSONDecodeError as e:
            log.warning("Visa LLM JSON parse error: %s", e)
        except Exception as e:
            log.warning("Visa LLM call error: %s", e)

        # Template fallback if LLM fails
        return self._template_fallback()

    def _enrich(self, result: dict, passport: str, dest: str,
                dest_name: str, passport_name: str, duration: int) -> dict:
        """Add always-correct metadata and official links."""

        # Official government travel advice links
        travel_links = {
            "GB": f"https://www.gov.uk/foreign-travel-advice/{dest.lower()}",
            "US": f"https://travel.state.gov/content/travel/en/international-travel/International-Travel-Country-Information-Pages/{dest_name.replace(' ','-')}.html",
            "AU": f"https://www.smartraveller.gov.au/destinations/{dest.lower()}",
            "CA": "https://travel.gc.ca/travelling/advisories",
        }

        result["official_advice_url"] = travel_links.get(passport,
            f"https://www.gov.uk/foreign-travel-advice/{dest.lower()}")

        result["iata_travel_centre"] = "https://www.iata.org/en/services/travel-and-visa/"

        result["disclaimer"] = (
            "⚠️ This is AI-generated guidance based on current knowledge. "
            "Entry requirements change frequently. Always verify with the "
            "official embassy of your destination country or your government's "
            "foreign travel advice service before booking."
        )

        # Add schengen 90/180 warning for UK travellers to Schengen zone
        if passport == "GB" and dest in SCHENGEN:
            if "travel_warnings" not in result:
                result["travel_warnings"] = []
            result["travel_warnings"].insert(0,
                "POST-BREXIT: UK passport holders are now third-country nationals "
                "in the Schengen Area. The 90-in-180-day rule applies across ALL "
                "Schengen countries combined, not per country."
            )

        result["source"] = "ai_llm_powered"
        return result

    def _template_fallback(self) -> dict:
        """Minimal safe fallback if LLM completely fails."""
        return {
            "visa_required":     "check_required",
            "entry_type":        "unknown",
            "max_stay_days":     None,
            "cost":              None,
            "processing_time":   None,
            "apply_url":         None,
            "passport_validity": "Check with destination country embassy",
            "requirements":      ["Contact destination country embassy for current requirements"],
            "health_requirements":[],
            "travel_warnings":   ["Always check your government's foreign travel advice"],
            "currency_tip":      "Check local currency requirements before travel",
            "emergency_contacts":{},
            "compliance_score":  0.5,
            "last_updated_note": "Could not retrieve AI-powered requirements. Please check official sources.",
            "summary":           "Unable to retrieve visa requirements at this time. Please check your government's official travel advice website and the destination country's embassy for entry requirements.",
        }

    def _score_confidence(self, result: dict) -> float:
        data  = result.get("data", {})
        score = float(data.get("compliance_score", 0.7))
        src   = data.get("source", "")
        if "ai_llm" in src:
            return min(0.95, score)
        return 0.65
