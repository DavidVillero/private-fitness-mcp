package local.fitness.bridge

/** Pure presentation state: 100% is reserved for a committed, acknowledged sync. */
data class ProgressViewState(val label:String,val percent:Int,val indeterminate:Boolean,val active:Boolean,val visible:Boolean)

fun progressViewState(phase:String,done:Int,total:Int,updated:Long,now:Long):ProgressViewState {
    val completed=done.coerceAtLeast(0)
    val percent=if(total>0) (completed.toLong()*100/total).coerceIn(0L,99L).toInt() else 0
    val running=phase in setOf("reading","connecting","uploading","committing")
    if(running && updated>0 && now-updated>120_000L)
        return ProgressViewState("Waiting for sync to resume. Your queued data is saved.",percent,false,false,true)
    return when(phase) {
        "queued" -> ProgressViewState("Waiting for Android to start the sync…",0,true,false,true)
        "reading" -> ProgressViewState("Reading Health Connect…",0,true,true,true)
        "connecting" -> ProgressViewState("Connecting securely to your Mac…",percent,true,true,true)
        "uploading" -> if(total>0) ProgressViewState("Sending ${completed.coerceAtMost(total)} of $total batches · $percent%",percent,false,true,true)
                       else ProgressViewState("Preparing the upload…",0,true,true,true)
        "committing" -> ProgressViewState("Finishing up…",99,false,true,true)
        "complete" -> ProgressViewState("Sync complete — your Mac has acknowledged the data.",100,false,false,true)
        "retry" -> ProgressViewState("Connection interrupted. Saved data will retry automatically.",percent,false,false,true)
        "oversized" -> ProgressViewState("A source record is too large. Data is retained; recovery needs attention.",percent,false,false,true)
        "error" -> ProgressViewState("Sync needs attention. Check permissions or your Mac connection.",percent,false,false,true)
        "paused" -> ProgressViewState("Hourly sync paused.",percent,false,false,false)
        else -> ProgressViewState("Ready to sync.",0,false,false,false)
    }
}
