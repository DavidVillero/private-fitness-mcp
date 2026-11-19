package local.fitness.bridge

import android.content.Context

object SyncProgress {
    fun update(context:Context,phase:String,done:Int=0,total:Int=0) {
        context.getSharedPreferences("sync-progress",Context.MODE_PRIVATE).edit()
            .putString("phase",phase).putInt("done",done).putInt("total",total)
            .putLong("updated",System.currentTimeMillis()).apply()
    }
    fun phase(context:Context,phase:String) {
        context.getSharedPreferences("sync-progress",Context.MODE_PRIVATE).edit()
            .putString("phase",phase).putLong("updated",System.currentTimeMillis()).apply()
    }
    fun view(context:Context):ProgressViewState {
        val p=context.getSharedPreferences("sync-progress",Context.MODE_PRIVATE)
        return progressViewState(p.getString("phase","idle") ?: "idle",p.getInt("done",0),p.getInt("total",0),p.getLong("updated",0),System.currentTimeMillis())
    }
}
