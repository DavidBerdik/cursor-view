// Resolve the `<img src>` for one attached image.
//
// Cache-backed chat detail (`/api/chat/:id`) ships image *metadata*
// only, so the byte source is the dedicated
// `GET /api/chat/:sessionId/image/:uuid` route. The desktop opened-file
// viewer (`/api/viewer/opened`) instead renders a JSON export whose
// images already carry inlined `data:` URIs (the export pipeline sets
// `include_image_bytes=True`), and that chat is not in the cache, so the
// API route would 404. Preferring an inlined `data_uri` when present
// lets `MessageImageGallery` / `ImageLightboxModal` serve both surfaces
// unchanged; the API-URL branch is byte-for-byte the previous behavior
// for cache-backed chats.
export function imageSrc(sessionId, img) {
  if (img && typeof img.data_uri === 'string' && img.data_uri.length > 0) {
    return img.data_uri;
  }
  return `/api/chat/${encodeURIComponent(sessionId)}/image/${encodeURIComponent(img.uuid)}`;
}
