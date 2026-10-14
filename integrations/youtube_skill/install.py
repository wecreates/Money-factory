"""Verify project-local discovery of the unchanged, pinned upstream skills."""
from pathlib import Path

NAMES = ('yt-audit','yt-chapters','yt-comment','yt-edit','yt-package','yt-plan',
         'yt-retention','yt-script','yt-seo','yt-shorts','yt-viral')


def verify_skills(root, upstream):
    root, upstream = Path(root), Path(upstream).resolve()
    for name in NAMES:
        target = upstream/'skills'/name
        if not (target/'SKILL.md').is_file():
            raise ValueError('Missing upstream skill: '+name)
        for directory in ('.claude/skills','.agents/skills'):
            link=root/directory/name
            if not link.is_symlink() or link.resolve(strict=True)!=target:
                raise ValueError('Project skill differs from pinned source: '+str(link))
    return list(NAMES)
