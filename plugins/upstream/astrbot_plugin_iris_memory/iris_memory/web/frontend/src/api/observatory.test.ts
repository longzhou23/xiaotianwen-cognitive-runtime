import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiGet, apiPost } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn()
}))

vi.mock('./request', () => ({ apiGet, apiPost }))

import {
  getObservatoryAdminEpisode,
  getObservatoryAdminEpisodes,
  getObservatoryAdminIdentity,
  getObservatoryAdminOutcomes,
  getObservatoryRuntimeDetail,
  getObservatoryEpisode,
  getObservatoryEpisodes,
  previewObservatoryReview
} from './observatory'

describe('Cognitive Observatory Episode ID transport', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('passes the exact listed Episode ID to the AstrBot bridge', async () => {
    const episodeId = 'episode:private:2986500364:runtime:136336110833632'
    apiGet
      .mockResolvedValueOnce({ success: true, episodes: [{ episode_id: episodeId }] })
      .mockResolvedValueOnce({ success: true, episode: { episode_id: episodeId } })

    const listing = await getObservatoryEpisodes()
    await getObservatoryEpisode(listing.episodes[0].episode_id)

    expect(apiGet).toHaveBeenNthCalledWith(1, 'cognitive-observatory/episodes', {})
    expect(apiGet).toHaveBeenNthCalledWith(
      2,
      `cognitive-observatory/episodes/${episodeId}`
    )
    expect(apiGet.mock.calls[1][0]).not.toContain('%3A')
  })

  it('uses the same unmodified ID for request-local Preview Review', async () => {
    const episodeId = 'episode:private:2986500364:runtime:136336110833632'
    apiPost.mockResolvedValue({ success: true, evidence_count: 0 })

    await previewObservatoryReview(episodeId)

    expect(apiPost).toHaveBeenCalledWith(
      `cognitive-observatory/episodes/${episodeId}/preview`,
      {}
    )
  })
})

describe('Cognitive Observatory runtime details', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('reads the dedicated redacted runtime-detail contract', async () => {
    const detail = { schema_version: 'iris.observatory-runtime-detail.v1', details: {} }
    apiGet.mockResolvedValue({ success: true, detail })

    await expect(getObservatoryRuntimeDetail()).resolves.toEqual(detail)
    expect(apiGet).toHaveBeenCalledWith('cognitive-observatory/runtime-detail')
  })

  it('fails closed when the detail endpoint is unavailable', async () => {
    apiGet.mockResolvedValue({ success: false, error: 'runtime detail unavailable' })

    await expect(getObservatoryRuntimeDetail()).rejects.toThrow('runtime detail unavailable')
  })
})

describe('Cognitive Observatory administrator record endpoints', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('passes bounded paging parameters for Identity, Episode, and Outcome records', async () => {
    apiGet
      .mockResolvedValueOnce({ success: true, schema: 'iris.observatory-admin-identity.v1' })
      .mockResolvedValueOnce({ success: true, schema: 'iris.observatory-admin-episode.v1' })
      .mockResolvedValueOnce({ success: true, schema: 'iris.observatory-admin-outcome.v1' })
      .mockResolvedValueOnce({ success: true, schema: 'iris.observatory-admin-episode.v1', episode: {} })

    await getObservatoryAdminIdentity({ limit: 20, offset: 40 })
    await getObservatoryAdminEpisodes({ limit: 20, offset: 40, state: 'FINALIZED' })
    await getObservatoryAdminOutcomes({ limit: 20, offset: 40 })
    await getObservatoryAdminEpisode('episode:admin:1')

    expect(apiGet).toHaveBeenNthCalledWith(1, 'cognitive-observatory/admin/identity', { limit: 20, offset: 40 })
    expect(apiGet).toHaveBeenNthCalledWith(2, 'cognitive-observatory/admin/episodes', { limit: 20, offset: 40, state: 'FINALIZED' })
    expect(apiGet).toHaveBeenNthCalledWith(3, 'cognitive-observatory/admin/outcomes', { limit: 20, offset: 40 })
    expect(apiGet).toHaveBeenNthCalledWith(4, 'cognitive-observatory/admin/episodes/episode:admin:1')
  })

  it('fails closed when an administrator record endpoint is unavailable', async () => {
    apiGet.mockResolvedValue({ success: false, error: 'admin records unavailable' })
    await expect(getObservatoryAdminIdentity()).rejects.toThrow('admin records unavailable')
  })
})
