"""
Shared pytest fixtures and configuration.
"""


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: mark test as integration (may hit real APIs)")
    config.addinivalue_line("markers", "slow: mark test as slow")
