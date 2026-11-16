"""Constants of the MARS Kinokasse integration."""

DOMAIN = "mars_kinokasse"

CONF_USER = "user_id"
CONF_SCREENS = "screens"
CONF_SCAN_MINUTES = "scan_minutes"
CONF_TOLERANCE = "tolerance_minutes"
CONF_DAY_START = "day_start"
CONF_KEEP_DAYS = "keep_days"
CONF_CALENDAR = "calendar_{}"  # .format(screen)

DEFAULT_PORT = 3080
DEFAULT_SCREENS = 3
DEFAULT_SCAN_MINUTES = 5
DEFAULT_TOLERANCE = 10
DEFAULT_DAY_START = "04:00:00"
DEFAULT_KEEP_DAYS = 183
DEFAULT_CALENDAR = "calendar.kino{}_dcp2000_spielplan"

TICK_SECONDS = 60  # server calendar and day values
SERVER_LOOKAHEAD_DAYS = 31
REQUEST_TIMEOUT = 20
STORE_VERSION = 1
