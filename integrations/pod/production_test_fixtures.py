"""Synthetic byte fixtures; not valid print products or acceptance evidence."""
COMMON_FILES = ('print.png', 'art-mask.png', 'text-mask.png', 'metadata.json',
                'research.json', 'provenance.json')
BOOK_FILES = ('cover.pdf', 'interior.pdf', 'interior.receipt.json')


def artifact_bodies(platform='kdp', overrides=None):
    names = COMMON_FILES + (BOOK_FILES if platform == 'kdp' else ())
    return {**dict.fromkeys(names, b''), **(overrides or {})}
