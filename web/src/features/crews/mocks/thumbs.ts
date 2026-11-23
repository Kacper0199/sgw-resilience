const found = import.meta.glob<string>("../../../../../data/artefacts/cv/thumbs/*.jpg", {
  eager: true,
  query: "?url",
  import: "default",
});

/** Mock-only: the committed 240 px thumbnail of a benchmark photo, so the mock API can answer the thumbnail route. */
export function mockThumbUrl(imageId: string): string | undefined {
  const file = imageId.replace(/^ladi-v2-/, "").replace("-", "_");
  return found[`../../../../../data/artefacts/cv/thumbs/${file}.jpg`];
}
