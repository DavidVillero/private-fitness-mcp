package local.fitness.bridge

import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

const val MAX_BATCH_BYTES = 2_000_000
const val MAX_HEART_SAMPLES = 10_000

/** Never truncate samples or change record IDs: updates/deletions depend on identity. */
class OversizedRecordException : IllegalArgumentException(
    "A source record exceeds the supported size. Data is retained; correct the source record before retrying."
)

fun batchBytes(value: JSONObject): ByteArray = value.toString().toByteArray(Charsets.UTF_8)

private fun objects(values: JSONArray) = (0 until values.length()).map { values.getJSONObject(it) }

/** Split by actual UTF-8 bytes, including the envelope, with stable IDs for crash replay. */
fun splitBatch(original: JSONObject): List<JSONObject> {
    val records = objects(original.getJSONArray("records"))
    val deletions = objects(original.getJSONArray("deletions"))
    for (record in records) {
        if (record.optString("kind") == "heart_rate" &&
            record.getJSONObject("data").getJSONArray("samples").length() > MAX_HEART_SAMPLES) {
            throw OversizedRecordException()
        }
    }
    if (batchBytes(original).size <= MAX_BATCH_BYTES && records.size + deletions.size <= 1000) {
        return listOf(original)
    }
    val result = mutableListOf<JSONObject>()
    val namespace = MessageDigest.getInstance("SHA-256")
        .digest(original.getString("batch_id").toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
    fun fresh() = batch(emptyList()).put("batch_id", "split-$namespace-${result.size}")
    var current = fresh()
    for ((key, values) in listOf("records" to records, "deletions" to deletions)) {
        for (value in values) {
            val candidate = JSONObject(current.toString())
            candidate.getJSONArray(key).put(value)
            val count = candidate.getJSONArray("records").length() + candidate.getJSONArray("deletions").length()
            if (count <= 1000 && batchBytes(candidate).size <= MAX_BATCH_BYTES) {
                current = candidate
            } else {
                if (current.getJSONArray("records").length() + current.getJSONArray("deletions").length() > 0) {
                    result.add(current)
                }
                current = fresh()
                current.getJSONArray(key).put(value)
                if (batchBytes(current).size > MAX_BATCH_BYTES) throw OversizedRecordException()
            }
        }
    }
    result.add(current)
    return result
}

/** Only rewrite the unsent suffix; persist atomically before exposing the new queue. */
fun repairUpload(envelope: JSONObject, persist: (JSONObject) -> Unit): JSONObject {
    val next = uploadIndex(envelope)
    val batches = envelope.getJSONArray("batches")
    val repaired = JSONArray()
    for (i in 0 until batches.length()) {
        val original = batches.getJSONObject(i)
        if (i < next) repaired.put(original)
        else splitBatch(original).forEach { repaired.put(it) }
    }
    if (repaired.toString() == batches.toString()) return envelope
    val saved = JSONObject(envelope.toString()).put("batches", repaired)
    persist(saved)
    return saved
}
