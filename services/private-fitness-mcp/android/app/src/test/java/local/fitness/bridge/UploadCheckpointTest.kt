package local.fitness.bridge

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class UploadCheckpointTest {
    private fun legacy()=JSONObject().put("batches",JSONArray().put(batch(emptyList())).put(batch(emptyList())))

    @Test fun legacyOutboxGetsOneStableCompletionReceipt() {
        val state=legacy()
        initializeUpload(state,true)
        val id=state.getString("completion_id")
        val restored=JSONObject(state.toString())
        initializeUpload(restored,true)
        assertEquals(3,restored.getJSONArray("batches").length())
        assertEquals(id,restored.getString("completion_id"))
        assertEquals(0,uploadIndex(restored))
    }

    @Test fun interruptionResumesAfterLastAcknowledgedBatch() {
        val state=legacy()
        initializeUpload(state,true)
        var disk=state.toString()
        checkpointUpload(state,1) { disk=it.toString() }
        val restored=JSONObject(disk)
        initializeUpload(restored,true)
        assertEquals(1,uploadIndex(restored))
        assertEquals(2,(uploadIndex(restored) until restored.getJSONArray("batches").length()).count())
        checkpointUpload(restored,2) { disk=it.toString() }
        checkpointUpload(restored,3) { disk=it.toString() }
        assertEquals(3,uploadIndex(JSONObject(disk)))
        assertTrue((uploadIndex(restored) until restored.getJSONArray("batches").length()).isEmpty())
    }

    @Test fun failedCheckpointDoesNotSkipAnUnpersistedBatch() {
        val state=legacy()
        initializeUpload(state,true)
        try {
            checkpointUpload(state,1) { throw java.io.IOException("Disk unavailable") }
            fail("Write should fail")
        } catch(_:java.io.IOException) { }
        assertEquals(0,uploadIndex(state))
    }

    @Test fun foregroundFinishingBackgroundOutboxIsNotBackgroundProof() {
        val state=legacy()
        initializeUpload(state,true)
        checkpointUpload(state,1) { }
        initializeUpload(state,false)
        assertEquals(3,state.getJSONArray("batches").length())
        assertEquals(1,uploadIndex(state))
        assertTrue(state.getString("completion_id").startsWith("sync-complete-foreground-"))
    }

    @Test(expected=IllegalArgumentException::class)
    fun cannotSkipUnacknowledgedBatches() {
        val state=legacy()
        initializeUpload(state,true)
        checkpointUpload(state,2) { }
    }

    @Test(expected=IllegalArgumentException::class)
    fun corruptCheckpointDoesNotSilentlyDiscardData() {
        val state=legacy().put("next_batch",99)
        initializeUpload(state,true)
    }
}
