package local.fitness.bridge

import android.content.Context
import androidx.work.*
import java.time.Instant
import java.util.concurrent.TimeUnit

object SyncSchedule {
    fun ensurePeriodic(context: Context) {
        val constraints=Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val work=PeriodicWorkRequestBuilder<SyncWorker>(1,TimeUnit.HOURS)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build()
        val manager=WorkManager.getInstance(context)
        manager.enqueueUniquePeriodicWork("fitness-sync",ExistingPeriodicWorkPolicy.KEEP,work)
    }
    fun enable(context: Context) {
        if(!SyncProgress.view(context).active) SyncProgress.update(context,"queued")
        ensurePeriodic(context)
        val constraints=Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val manager=WorkManager.getInstance(context)
        val initial=OneTimeWorkRequestBuilder<SyncWorker>().setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build()
        manager.enqueueUniqueWork("fitness-sync-now",ExistingWorkPolicy.KEEP,initial)
        context.getSharedPreferences("sync-status",Context.MODE_PRIVATE).edit().putBoolean("enabled",true).apply()
    }
    fun disable(context: Context) {
        val manager=WorkManager.getInstance(context)
        manager.cancelUniqueWork("fitness-sync");manager.cancelUniqueWork("fitness-sync-now")
        context.getSharedPreferences("sync-status",Context.MODE_PRIVATE).edit().putBoolean("enabled",false).apply()
        if(!SyncProgress.view(context).active) SyncProgress.phase(context,"paused")
    }
    fun noteUnverifiedDeletions(context: Context, stream: String) {
        val prefs = context.getSharedPreferences("sync-status", Context.MODE_PRIVATE)
        val seen = prefs.getStringSet("unverified-deletions", emptySet())?.toMutableSet() ?: mutableSetOf()
        seen.add(stream)
        check(prefs.edit().putStringSet("unverified-deletions", seen).commit())
    }
    fun hasUnverifiedDeletions(context: Context): Boolean =
        !context.getSharedPreferences("sync-status", Context.MODE_PRIVATE)
            .getStringSet("unverified-deletions", emptySet()).isNullOrEmpty()
    fun record(context:Context,status:String,success:Boolean=false) {
        val editor=context.getSharedPreferences("sync-status",Context.MODE_PRIVATE).edit().putString("status",status)
        if(success) editor.putString("last_success",Instant.now().toString())
        editor.apply()
    }
    fun summary(context:Context):String {
        val prefs=context.getSharedPreferences("sync-status",Context.MODE_PRIVATE)
        val warning = if(hasUnverifiedDeletions(context))
            " Warning: expired change tokens were recovered by a 30-day reread, but missed deletions and older revisions are NOT verified; review the stored history."
            else ""
        return "Hourly sync: ${if(prefs.getBoolean("enabled",false)) "enabled" else "off"}. " +
            "Status: ${prefs.getString("status","not run")}. Last success: ${prefs.getString("last_success","none")}." + warning
    }
}
