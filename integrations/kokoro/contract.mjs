export function assertCompleteText(original, segments) {
  if (!segments.length || segments.some(x => !Number.isInteger(x.phoneme_tokens) || x.phoneme_tokens < 1 || x.phoneme_tokens > 511)) {
    throw Error('Refusing empty or truncated utterances');
  }
  const normalized = value => value.replace(/\s+/g, ' ').trim();
  if (normalized(segments.map(x => x.text).join(' ')) !== normalized(original)) {
    throw Error('Text segmentation changed source');
  }
}
