package local.fitness.bridge

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class BatchingTest {
    private fun record(id: Int, size: Int = 230_000) = obj(
        "record_id" to "$id", "kind" to "synthetic", "payload" to "é".repeat(size)
    )
    private fun huge() = batch((1..10).map { record(it) }).put("batch_id", "legacy-large")

    @Test fun measuresUtf8AndPreservesEveryIdentityInOrder() {
        val parts = splitBatch(huge())
        assertTrue(parts.size > 1)
        assertTrue(parts.all { batchBytes(it).size <= MAX_BATCH_BYTES })
        val ids = parts.flatMap { part ->
            val records = part.getJSONArray("records")
            (0 until records.length()).map { records.getJSONObject(it).getString("record_id") }
        }
        assertEquals((1..10).map { "$it" }, ids)
        assertEquals(parts.map { it.toString() }, splitBatch(huge()).map { it.toString() })
    }

    @Test fun repairKeepsAcknowledgedPrefixAndResumesAfterCrash() {
        val prefix = batch(emptyList())
        val state = obj("batches" to JSONArray().put(prefix).put(huge()), "next_batch" to 1)
        var disk = state.toString()
        val repaired = repairUpload(state) { disk = it.toString() }
        assertEquals(prefix.toString(), repaired.getJSONArray("batches").getJSONObject(0).toString())
        assertEquals(1, uploadIndex(repaired))
        val restored = repairUpload(JSONObject(disk)) { fail("Already repaired") }
        assertEquals(repaired.toString(), restored.toString())
        checkpointUpload(restored, 2) { disk = it.toString() }
        assertEquals(2, uploadIndex(repairUpload(JSONObject(disk)) { fail("Already repaired") }))
    }

    @Test fun failedAtomicRepairLeavesOriginalUnchanged() {
        val state = obj("batches" to JSONArray().put(huge()))
        val before = state.toString()
        try {
            repairUpload(state) { throw java.io.IOException("Disk full") }
            fail("Expected failure")
        } catch (_: java.io.IOException) { }
        assertEquals(before, state.toString())
    }

    @Test fun lostAckReplayHasStableIdsAndContents() {
        val state = obj("batches" to JSONArray().put(huge()))
        val first = repairUpload(state) { }.toString()
        assertEquals(first, repairUpload(JSONObject(state.toString())) { }.toString())
    }

    @Test(expected=OversizedRecordException::class)
    fun singleOversizedRecordIsNeverTruncated() { splitBatch(batch(listOf(record(1, 1_100_000)))) }

    @Test(expected=OversizedRecordException::class)
    fun tooManySamplesAreExplicitlyUnsupported() {
        val samples = JSONArray()
        repeat(MAX_HEART_SAMPLES + 1) { samples.put(obj("time" to "2020-01-01T00:00:00Z", "bpm" to 60)) }
        splitBatch(batch(listOf(obj("kind" to "heart_rate", "data" to obj("samples" to samples)))))
    }

    @Test fun deletionOnlyBatchesRespectCountAndPreserveAllEntries() {
        val parts = splitBatch(batch(emptyList(), (1..1001).map { obj("record_id" to "$it") }))
        assertEquals(listOf(1000, 1), parts.map { it.getJSONArray("deletions").length() })
        assertTrue(parts.all { batchBytes(it).size <= MAX_BATCH_BYTES })
    }
    @Test fun expiredTokenRecoveryUsesLastThirtyDays() {
        val now = java.time.Instant.parse("2026-11-16T12:00:00Z")
        assertEquals(java.time.Instant.parse("2026-10-17T12:00:00Z"), tokenRecoveryStart(now))
    }
}
