/** The queue serves its own thumbnails: `ladi-v2-test-0016` is `GET /api/damage/thumbs/ladi-v2-test-0016`. */
export const thumbUrl = (imageId: string): string => `/api/damage/thumbs/${encodeURIComponent(imageId)}`;
