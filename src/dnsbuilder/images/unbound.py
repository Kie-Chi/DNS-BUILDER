from .image import Image

class UnboundImage(Image):
    """
    Concrete Image class for Unbound.
    """
    def _post_init_hook(self):
        """
            Nothing to do
        """
        pass # Unbound has nothing to do