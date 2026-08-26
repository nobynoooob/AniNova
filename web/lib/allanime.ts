import { EpisodeEntry, StreamSource } from "./types";

/**
 * AllAnime direct resolver — TypeScript port of the desktop app's proven
 * `ani_cli_arabic/scrapers/allanime.py` client-crypto handshake.
 *
 * 1. x-aa-boot HMAC token from the build mask
 * 2. GET /client-crypto/v1/bootstrap -> partB + epoch
 * 3. AES-256-GCM key = partB XOR mask
 * 4. aaReq = base64(0x01 | iv[12] | ct | tag[16]) over
 *    {v,ts,epoch,buildId,qh,k}; iv = sha256(`${epoch}:98:${qh}:${ts}:k7`)[0:12]
 * 5. GraphQL POST with the site's exact episode query + persistedQuery hash
 * 6. decrypt `tobeparsed` (tag in LAST 16 bytes) -> real sourceUrls
 *
 * No third-party extraction API involved.
 */
import crypto from "node:crypto";

const BUILD_ID = "98";
const LANE = "k7";
const MASK = Buffer.from(
  "a425a35301cacc46a6436789939cb8767730f84100faea5d7e772cc94a31de65",
  "hex"
);
const EPOCH_MS = 604800000;
const SWITCH_MS = 86400000;
const API_BASE = "https://api.mkissa.net/api";
const BOOTSTRAP_URL =
  "https://api.mkissa.net/client-crypto/v1/bootstrap?buildId=98&k=k7";
const REFERRER = "https://mkissa.to";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36";

// The site's exact episode query text — the accepted persistedQuery hash is
// the SHA-256 of THIS EXACT TEXT. Do not reformat.
const EPISODE_QUERY = `query(
$showId: String!
$translationType: VaildTranslationTypeEnumType!
$episodeString: String!
) {
episode(
showId: $showId
translationType: $translationType
episodeString: $episodeString
) {
episodeString
uploadDate
sourceUrls
thumbnail
notes
show{


_id
name
englishName
nativeName
slugTime

thumbnail

tbObj {
  u
  sm
  md
  ts
}

lastEpisodeInfo
lastEpisodeDate
type
season
score
airedStart
availableEpisodes
episodeDuration
episodeCount
# lastUpdateStart
lastUpdateEnd
characterCount

description
broadcastInterval
banner
characters
availableEpisodesDetail
nameOnlyString
characters
isAdult
relatedShows
relatedMangas
altNames
disqusIds
}
pageStatus{
_id
notes
pageId
showId

views
userScoreCount
userScoreAverValue
likesCount
commentCount
dislikesCount
boostsCount
reviewCount

}
episodeInfo{
notes
thumbnails

tbObj {
  u
  sm
  md
  ts
}

vidInforssub
uploadDates
vidInforsdub
vidInforsraw
description
}
versionFix
}
}
`;

const EPISODE_QUERY_HASH = crypto
  .createHash("sha256")
  .update(EPISODE_QUERY)
  .digest("hex");

const SEARCH_QUERY = `query($search: SearchInput $limit: Int $page: Int $translationType: VaildTranslationTypeEnumType $countryOrigin: VaildCountryOriginEnumType) { shows(search: $search limit: $limit page: $page translationType: $translationType countryOrigin: $countryOrigin) { edges { _id name availableEpisodes __typename } } }`;

const SHOW_QUERY = `query ($showId: String!) { show( _id: $showId ) { _id name availableEpisodesDetail availableEpisodes }}`;

const HEX_REMAP: Record<string, string> = {
  "79": "A", "7a": "B", "7b": "C", "7c": "D", "7d": "E", "7e": "F", "7f": "G",
  "70": "H", "71": "I", "72": "J", "73": "K", "74": "L", "75": "M", "76": "N",
  "77": "O", "68": "P", "69": "Q", "6a": "R", "6b": "S", "6c": "T", "6d": "U",
  "6e": "V", "6f": "W", "60": "X", "61": "Y", "62": "Z",
  "59": "a", "5a": "b", "5b": "c", "5c": "d", "5d": "e", "5e": "f", "5f": "g",
  "50": "h", "51": "i", "52": "j", "53": "k", "54": "l", "55": "m", "56": "n",
  "57": "o", "48": "p", "49": "q", "4a": "r", "4b": "s", "4c": "t", "4d": "u",
  "4e": "v", "4f": "w", "40": "x", "41": "y", "42": "z",
  "08": "0", "09": "1", "0a": "2", "0b": "3", "0c": "4", "0d": "5", "0e": "6",
  "0f": "7", "00": "8", "01": "9",
  "15": "-", "16": ".", "67": "_", "46": "~", "02": ":", "17": "/", "07": "?",
  "1b": "#", "63": "[", "65": "]", "78": "@", "19": "!", "1c": "$", "1e": "&",
  "10": "(", "11": ")", "12": "*", "13": "+", "14": ",", "03": ";", "05": "=",
  "1d": "%",
};

function decodeObfuscated(url: string): string {
  if (!url.startsWith("--")) return url;
  const hexed = url.slice(2);
  let out = "";
  for (let i = 0; i + 1 < hexed.length; i += 2) {
    out += HEX_REMAP[hexed.slice(i, i + 2).toLowerCase()] || "?";
  }
  return out;
}

function epochFor(nowMs: number): number {
  const t = Math.floor(nowMs / EPOCH_MS);
  if (t > 0 && nowMs - t * EPOCH_MS < SWITCH_MS) return t - 1;
  return t;
}

function bootToken(mask: Buffer, epoch: number): string {
  const h = crypto.createHmac("sha256", mask).update(`aa-boot:${BUILD_ID}`).digest();
  return crypto
    .createHmac("sha256", h)
    .update(`${BUILD_ID}:mkissa:mkissa.to:${epoch}:${LANE}`)
    .digest("hex");
}

function deriveKey(partB: string): Buffer {
  const pb = Buffer.from(partB, "base64");
  const out = Buffer.alloc(Math.max(pb.length, MASK.length));
  for (let i = 0; i < out.length; i++) {
    out[i] = (pb[i] || 0) ^ (MASK[i] || 0);
  }
  return out.subarray(0, 32);
}

function makeAaReq(key: Buffer, epoch: number, qh: string, ts: number): string {
  const payload = JSON.stringify({
    v: 1,
    ts,
    epoch,
    buildId: BUILD_ID,
    qh,
    k: LANE,
  });
  const iv = crypto
    .createHash("sha256")
    .update(`${epoch}:${BUILD_ID}:${qh}:${ts}:${LANE}`)
    .digest()
    .subarray(0, 12);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([cipher.update(payload, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([Buffer.from([1]), iv, ct, tag]).toString("base64");
}

function decryptTobeparsed(tobeparsed: string, key: Buffer): unknown | null {
  try {
    const raw = Buffer.from(tobeparsed, "base64");
    if (raw.length < 1 + 12 + 16) return null;
    const iv = raw.subarray(1, 13);
    const tag = raw.subarray(raw.length - 16);
    const ct = raw.subarray(13, raw.length - 16);
    const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
    decipher.setAuthTag(tag);
    const pt = Buffer.concat([decipher.update(ct), decipher.final()]).toString(
      "utf8"
    );
    return JSON.parse(pt);
  } catch {
    return null;
  }
}

async function post(query: string, variables: unknown, aa?: unknown) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 9000);
  try {
    const payload: Record<string, unknown> = { query, variables };
    if (aa) payload.extensions = aa;
    const res = await fetch(API_BASE, {
      method: "POST",
      headers: {
        "User-Agent": UA,
        Referer: REFERRER,
        "Content-Type": "application/json",
        "x-build-id": BUILD_ID,
      },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
      cache: "no-store",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

async function bootstrap(): Promise<{ partB: string; epoch: number } | null> {
  try {
    const epoch = epochFor(Date.now());
    const res = await fetch(BOOTSTRAP_URL, {
      headers: {
        "User-Agent": UA,
        "x-build-id": BUILD_ID,
        "x-aa-boot": bootToken(MASK, epoch),
        Origin: REFERRER,
        Referer: REFERRER + "/",
      },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { partB?: string; epoch?: number };
    if (data.partB && data.epoch != null) {
      return { partB: data.partB, epoch: data.epoch };
    }
    return null;
  } catch {
    return null;
  }
}

export interface AllAnimeShow {
  id: string;
  name: string;
}

export async function allanimeSearch(query: string): Promise<AllAnimeShow[]> {
  const data = (await post(SEARCH_QUERY, {
    search: { allowAdult: false, allowUnknown: false, query },
    limit: 20,
    page: 1,
    translationType: "sub",
    countryOrigin: "ALL",
  })) as {
    data?: { shows?: { edges?: { _id?: string; name?: string }[] } };
  } | null;
  const edges = data?.data?.shows?.edges || [];
  return edges
    .filter((e) => e._id)
    .map((e) => ({ id: String(e._id), name: String(e.name || "") }));
}

export async function allanimeEpisodes(
  showId: string
): Promise<EpisodeEntry[]> {
  const data = (await post(SHOW_QUERY, { showId })) as {
    data?: { show?: { availableEpisodesDetail?: Record<string, string[]> } };
  } | null;
  const detail = data?.data?.show?.availableEpisodesDetail || {};
  const list = detail.sub || detail.dub || [];
  return list
    .map((e) => ({ num: Number(e), id: `${showId}/${e}` }))
    .filter((e) => Number.isFinite(e.num) && e.num > 0)
    .sort((a, b) => a.num - b.num);
}

export async function allanimeSources(
  showId: string,
  episodeString: string
): Promise<StreamSource[]> {
  const boot = await bootstrap();
  if (!boot) throw new Error("AllAnime bootstrap unavailable");
  const key = deriveKey(boot.partB);
  const ts = Math.floor(Date.now() / 300000) * 300000;
  const aaReq = makeAaReq(key, boot.epoch, EPISODE_QUERY_HASH, ts);

  const data = (await post(
    EPISODE_QUERY,
    { showId, translationType: "sub", episodeString },
    {
      persistedQuery: { version: 1, sha256Hash: EPISODE_QUERY_HASH },
      k: LANE,
      aaReq,
    }
  )) as {
    data?: {
      tobeparsed?: string;
      episode?: { sourceUrls?: { sourceUrl?: string; sourceName?: string }[] };
    };
  } | null;
  if (!data) throw new Error("AllAnime episode query failed");

  let urls: { sourceUrl?: string; sourceName?: string }[] = [];
  if (data.data?.tobeparsed) {
    const decrypted = decryptTobeparsed(data.data.tobeparsed, key) as {
      episode?: { sourceUrls?: { sourceUrl?: string; sourceName?: string }[] };
    } | null;
    urls = decrypted?.episode?.sourceUrls || [];
  } else {
    urls = data.data?.episode?.sourceUrls || [];
  }

  const out: StreamSource[] = [];
  let genericIdx = 1;
  for (const u of urls) {
    const src = decodeObfuscated(u.sourceUrl || "").trim();
    if (!src) continue;
    if (src.startsWith("http") && /\.(m3u8|mp4)/i.test(src.split("?")[0])) {
      out.push({
        server: (u.sourceName || `src-${genericIdx}`).toLowerCase(),
        url: `/api/stream?url=${encodeURIComponent(src)}`,
        raw: src,
      });
      genericIdx++;
    }
  }
  return out;
}
