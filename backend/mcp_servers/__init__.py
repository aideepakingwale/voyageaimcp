from .flight_mcp     import FlightMCP
from .hotel_mcp      import HotelMCP
from .car_mcp        import CarMCP
from .weather_mcp    import WeatherMCP
from .maps_mcp       import MapsMCP
from .currency_mcp   import CurrencyMCP
from .visa_mcp       import VisaMCP
from .experience_mcp import ExperienceMCP
from .customer_mcp   import CustomerMCP
from .loyalty_mcp    import LoyaltyMCP
from .ancillary_mcp  import AncillaryMCP

MCP_REGISTRY = {
    "flights":     FlightMCP(),
    "hotels":      HotelMCP(),
    "cars":        CarMCP(),
    "weather":     WeatherMCP(),
    "maps":        MapsMCP(),
    "currency":    CurrencyMCP(),
    "visa":        VisaMCP(),
    "experiences": ExperienceMCP(),
    "customer":    CustomerMCP(),
    "loyalty":     LoyaltyMCP(),
    "ancillaries": AncillaryMCP(),
}
