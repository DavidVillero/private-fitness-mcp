package local.fitness.bridge

import org.json.JSONObject

/** Legacy outboxes start at zero; a completion receipt is added exactly once. */
fun initializeUpload(envelope:JSONObject,background:Boolean) {
    val batches=envelope.getJSONArray("batches")
    require(batches.length()>0)
    val next=uploadIndex(envelope)
    val mode=if(background) "background" else "foreground"
    val id="sync-complete-$mode-"+batches.getJSONObject(0).getString("batch_id")
    if(!envelope.has("completion_id")) {
        batches.put(batch(emptyList()).put("batch_id",id))
        envelope.put("completion_id",id)
    } else if(next<batches.length() && envelope.getString("completion_id")!=id) {
        // Attribute an unsent completion receipt to the run that finishes it.
        batches.put(batches.length()-1,batch(emptyList()).put("batch_id",id))
        envelope.put("completion_id",id)
    }
    uploadIndex(envelope)
}

fun uploadIndex(envelope:JSONObject):Int {
    val next=envelope.optInt("next_batch",0)
    require(next in 0..envelope.getJSONArray("batches").length()) { "Invalid upload checkpoint" }
    return next
}

/** Caller invokes only after a matching server ACK. Never advance memory on write failure. */
fun checkpointUpload(envelope:JSONObject,next:Int,persist:(JSONObject)->Unit) {
    require(next==uploadIndex(envelope)+1 && next<=envelope.getJSONArray("batches").length())
    val saved=JSONObject(envelope.toString()).put("next_batch",next)
    persist(saved)
    envelope.put("next_batch",next)
}
