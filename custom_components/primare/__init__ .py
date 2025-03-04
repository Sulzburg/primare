import logging
_LOGGER = logging.getLogger(__name__)
def setup(hass, config):
    """Set up the Primare component."""
    _LOGGER.info("Primare Component wurde geladen.")
    return True
