from .gpv import GamePointVolleyballAdapter
from .wpvc import WPVCAdapter
from .ova import OVAAdapter
from .outsports import OutSportsLeagueAdapter
from .aes import AESAdapter
from .govc import GreaterOrlandoVolleyballClubAdapter
from .nagva import NAGVAAdapter
from .bighouse import BigHouseOpenGymAdapter
from .sanford import SanfordAdultVolleyballAdapter
from .volleyvortex import VolleyVortexAdapter
from .goldenrod import GoldenrodCommunityParkAdapter
# from .ymca import YMCACentralFloridaAdapter  # disabled -- see note below
from .volleyballlife import VolleyballLifeAdapter
from .ocoee import OcoeeCoedLeagueAdapter, OcoeeOpenGymAdapter
from .usavflorida import USAVFloridaRegionAdapter
from .community import CommunityEventsAdapter
from .meadowwoods import MeadowWoodsRecreationCenterAdapter
from .ssova import SSOVAAdapter

ALL_ADAPTERS = [
    GamePointVolleyballAdapter,
    WPVCAdapter,
    OVAAdapter,
    OutSportsLeagueAdapter,
    AESAdapter,
    GreaterOrlandoVolleyballClubAdapter,
    NAGVAAdapter,
    BigHouseOpenGymAdapter,
    SanfordAdultVolleyballAdapter,
    VolleyVortexAdapter,
    GoldenrodCommunityParkAdapter,
    # YMCACentralFloridaAdapter,  # disabled: .ymca-event-card never attaches
    # to the DOM within 60s from this scraper's network, even isolated from
    # every other adapter -- confirmed it's not a timeout-tuning problem.
    # Re-enable by uncommenting this and the import above once revisited
    # (e.g. check for bot-blocking/rate-limiting, or find an API endpoint
    # the page's widget calls instead of rendering the full page).
    VolleyballLifeAdapter,
    OcoeeCoedLeagueAdapter,
    OcoeeOpenGymAdapter,
    USAVFloridaRegionAdapter,
    CommunityEventsAdapter,
    MeadowWoodsRecreationCenterAdapter,
    SSOVAAdapter,
]
