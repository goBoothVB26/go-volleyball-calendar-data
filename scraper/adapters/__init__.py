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
from .ymca import YMCACentralFloridaAdapter
from .volleyballlife import VolleyballLifeAdapter
from .ocoee import OcoeeCoedLeagueAdapter, OcoeeOpenGymAdapter
from .usavflorida import USAVFloridaRegionAdapter
from .community import CommunityEventsAdapter
from .meadowwoods import MeadowWoodsRecreationCenterAdapter

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
    YMCACentralFloridaAdapter,
    VolleyballLifeAdapter,
    OcoeeCoedLeagueAdapter,
    OcoeeOpenGymAdapter,
    USAVFloridaRegionAdapter,
    CommunityEventsAdapter,
    MeadowWoodsRecreationCenterAdapter,
]
