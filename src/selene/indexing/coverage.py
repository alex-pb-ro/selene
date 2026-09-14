"""Conservative filesystem eligibility for native event-driven observations."""

import sys
from pathlib import Path

import psutil

from selene.indexing.scope import IndexInclusionPolicy


class NativeWatchCoverage:
    """Reject unknown and shared filesystems whose external writes may not emit local events."""

    _LOCAL_FILESYSTEMS = {
        "darwin": {"apfs", "hfs", "ufs"},
        "linux": {"ext2", "ext3", "ext4", "xfs", "btrfs", "tmpfs", "ramfs", "overlay"},
    }

    @classmethod
    def reconciliation_reason(cls, root: Path, policy: IndexInclusionPolicy) -> str | None:
        supported = cls._LOCAL_FILESYSTEMS.get(sys.platform)
        if supported is None:
            return "unsupported_native_watcher"
        partitions = psutil.disk_partitions(all=True)
        ancestors = [partition for partition in partitions if root.is_relative_to(Path(partition.mountpoint))]
        if not ancestors:
            return "unknown_project_filesystem"
        containing = max(ancestors, key=lambda partition: len(Path(partition.mountpoint).parts))
        selected = [containing]
        for partition in partitions:
            mount = Path(partition.mountpoint)
            if mount.is_relative_to(root) and policy.includes(mount.relative_to(root).as_posix(), directory=True):
                selected.append(partition)
        if any(partition.fstype not in supported for partition in selected):
            return "filesystem_requires_reconciliation"
        return None
