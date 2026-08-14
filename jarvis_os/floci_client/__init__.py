"""Floci Client — async AWS S3 + SQS client for the Jarvis media pipeline."""

from jarvis_os.floci_client.client import (
    BucketNotFoundError,
    DownloadError,
    FlociClient,
    FlociError,
    QueueNotFoundError,
    UploadError,
)
from jarvis_os.floci_client.models import (
    BucketType,
    FlociConfig,
    S3Object,
    SQSMessage,
    SQSQueue,
)

__all__ = [
    "BucketType",
    "BucketNotFoundError",
    "DownloadError",
    "FlociClient",
    "FlociConfig",
    "FlociError",
    "QueueNotFoundError",
    "S3Object",
    "SQSMessage",
    "SQSQueue",
    "UploadError",
    "__version__",
]

__version__ = "0.1.0"
