"""
Gateway Service Routers Package
"""

# Import routers with fallbacks
try:
    from . import health
except ImportError as e:
    print(f"Warning: Could not import health router: {e}")
    health = None

try:
    from . import monitoring
except ImportError as e:
    print(f"Warning: Could not import monitoring router: {e}")
    monitoring = None

try:
    from . import webhooks
except ImportError as e:
    print(f"Warning: Could not import webhooks router: {e}")
    webhooks = None

try:
    from . import conversations
except ImportError as e:
    print(f"Warning: Could not import conversations router: {e}")
    conversations = None

try:
    from . import messages
except ImportError as e:
    print(f"Warning: Could not import messages router: {e}")
    messages = None

# Only include successfully imported routers
__all__ = []
for router_name, router in [
    ("health", health),
    ("monitoring", monitoring),
    ("webhooks", webhooks),
    ("conversations", conversations),
    ("messages", messages)
]:
    if router is not None:
        __all__.append(router_name)