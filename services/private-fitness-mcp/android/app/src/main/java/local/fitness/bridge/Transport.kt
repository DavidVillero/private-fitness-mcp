package local.fitness.bridge

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import android.os.SystemClock
import java.net.InetAddress
import java.net.URL
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.net.ssl.HttpsURLConnection

val SYNC_LOCK = Mutex()

class RetryableSyncException: java.io.IOException("Temporary ingestion failure")
class TerminalSyncException: IllegalStateException("Ingestion rejected; check pairing or validation")

class Vault(private val context: Context) {
    private val prefs = context.getSharedPreferences("connection",Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val store=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!store.containsAlias("fitness-ingestion")) {
            KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder("fitness-ingestion",KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
            }.generateKey()
        }
        return store.getKey("fitness-ingestion",null) as SecretKey
    }
    fun save(endpoint: String, token: String) {
        val url=URL(endpoint)
        require(url.protocol=="https" && url.userInfo==null && url.path=="/v1/ingest" && url.query==null && url.ref==null)
        require(token.length>=32)
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key())
        val encrypted=cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString("endpoint",endpoint).putString("iv",Base64.encodeToString(cipher.iv,Base64.NO_WRAP))
            .putString("ciphertext",Base64.encodeToString(encrypted,Base64.NO_WRAP)).commit())
    }
    fun importUsbPairing():Boolean {
        val file=java.io.File(context.filesDir,"mac-pairing.json")
        if(!file.exists()) return false
        require(file.length()<=8192) { "Invalid pairing file" }
        val data=JSONObject(file.readText())
        require(data.getInt("schema_version")==1)
        save(data.getString("endpoint"),data.getString("token"))
        check(file.delete()) { "Remove consumed pairing file" }
        return true
    }
    fun endpoint()=prefs.getString("endpoint",null) ?: error("Configure private HTTPS endpoint first")
    fun token(): String {
        val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE,key(),GCMParameterSpec(128,Base64.decode(prefs.getString("iv",null) ?: error("Pair first"),Base64.NO_WRAP)))
        return String(cipher.doFinal(Base64.decode(prefs.getString("ciphertext",null),Base64.NO_WRAP)),Charsets.UTF_8)
    }
}

private fun privateAddress(a: InetAddress): Boolean {
    val b=a.address
    val tailscaleV4=b.size==4 && b[0].toInt().and(255)==100 && b[1].toInt().and(255) in 64..127
    val uniqueLocalV6=b.size==16 && b[0].toInt().and(254)==252
    return a.isSiteLocalAddress || a.isLoopbackAddress || tailscaleV4 || uniqueLocalV6
}

suspend fun upload(context: Context,background:Boolean=false): Int = SYNC_LOCK.withLock {
    val grants=HealthConnectClient.getOrCreate(context).permissionController.getGrantedPermissions()
    require(READ_PERMISSIONS.any { it in grants }) { "Grant Health Connect read access first" }
    SyncProgress.update(context,"connecting")
    val vault=Vault(context);val url=URL(vault.endpoint())
    require(InetAddress.getAllByName(url.host).all { privateAddress(it) }) { "Endpoint must resolve exclusively to private network addresses" }
    SyncProgress.update(context,"reading")
    val deadline=if(background) SystemClock.elapsedRealtime()+4*60*1000L else Long.MAX_VALUE
    var acknowledged=0
    var networkFailure=false
    var attention=false
    var oversized=false
    val observations=context.getSharedPreferences("source-observations",Context.MODE_PRIVATE)
    for(bridge in sourceStreams(context)) {
        context.getSharedPreferences("sync-progress",Context.MODE_PRIVATE).edit()
            .putString("source",if(bridge.origin==GARMIN) "Garmin" else "Zepp").apply()
        try {
            currentCoroutineContext().ensureActive()
            if(SystemClock.elapsedRealtime()>=deadline)throw RetryableSyncException()
            val envelope=bridge.prepareUpload(background)
            if(envelope.optBoolean("skipped",false))continue
            val batches=envelope.getJSONArray("batches")
            val resumeAt=uploadIndex(envelope)
            SyncProgress.update(context,"uploading",resumeAt,batches.length())
            for(i in resumeAt until batches.length()) {
                currentCoroutineContext().ensureActive()
                if(SystemClock.elapsedRealtime()>=deadline)throw RetryableSyncException()
                val connection=url.openConnection() as HttpsURLConnection
                connection.instanceFollowRedirects=false;connection.connectTimeout=15000;connection.readTimeout=30000
                connection.requestMethod="POST";connection.doOutput=true
                connection.setRequestProperty("Content-Type","application/json")
                connection.setRequestProperty("Authorization","Bearer ${vault.token()}")
                val bytes=batchBytes(batches.getJSONObject(i))
                require(bytes.size<=MAX_BATCH_BYTES) { "Batch too large; split required" }
                try {
                    connection.setFixedLengthStreamingMode(bytes.size)
                    connection.outputStream.use { it.write(bytes) }
                    val code=connection.responseCode
                    if(code in listOf(408,425,429,500,502,503,504)) throw RetryableSyncException()
                    if(code!=200) throw TerminalSyncException()
                    val ack=JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
                    check(ack.has("accepted") && ack.has("duplicate_batch") &&
                        ack.optString("batch_id")==batches.getJSONObject(i).getString("batch_id")) { "Invalid acknowledgment" }
                } finally { connection.disconnect() }
                bridge.checkpoint(envelope,i+1)
                SyncProgress.update(context,"uploading",i+1,batches.length())
            }
            SyncProgress.phase(context,"committing")
            bridge.acknowledge(envelope)
            acknowledged+=batches.length()
            // Metadata-only local evidence; zero new rows does not mean no historical records.
            observations.edit().putLong(bridge.origin+"-last_success",System.currentTimeMillis()).apply()
        } catch(e:CancellationException) { throw e }
        catch(_:java.io.IOException) { networkFailure=true;break }
        catch(_:OversizedRecordException) { oversized=true }
        catch(_:SecurityException) { attention=true }
        catch(_:IllegalArgumentException) { attention=true }
        catch(_:IllegalStateException) { attention=true }
        // A failed Zepp/extra stream must never prevent the legacy Garmin stream
        // from running on this or subsequent syncs. Each cursor commits separately.
    }
    if(networkFailure)throw RetryableSyncException()
    if(oversized)throw OversizedRecordException()
    if(attention)throw TerminalSyncException()
    SyncProgress.update(context,"complete",acknowledged,acknowledged)
    acknowledged
}

class SyncWorker(context: Context,params: WorkerParameters): CoroutineWorker(context,params) {
    override suspend fun doWork(): Result {
        return try {
            val grants=HealthConnectClient.getOrCreate(applicationContext).permissionController.getGrantedPermissions()
            if (HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND !in grants) {
                SyncProgress.phase(applicationContext,"error")
                SyncSchedule.record(applicationContext,"background_permission_required")
                return Result.failure()
            }
            SyncSchedule.record(applicationContext,"syncing")
            upload(applicationContext,background=true)
            SyncSchedule.record(applicationContext, if (SyncSchedule.hasUnverifiedDeletions(applicationContext)) "ok_with_unverified_deletions" else "ok", success=true)
            Result.success()
        } catch(e: CancellationException) { SyncProgress.phase(applicationContext,"retry");throw e }
        catch(_: OversizedRecordException) { SyncProgress.phase(applicationContext,"oversized");SyncSchedule.record(applicationContext,"source_record_too_large");Result.failure() }
        catch(_: SecurityException) { SyncProgress.phase(applicationContext,"error");SyncSchedule.record(applicationContext,"permission_required");Result.failure() }
        catch(_: IllegalArgumentException) { SyncProgress.phase(applicationContext,"error");SyncSchedule.record(applicationContext,"pairing_or_permission_review_required");Result.failure() }
        catch(_: IllegalStateException) { SyncProgress.phase(applicationContext,"error");SyncSchedule.record(applicationContext,"pairing_or_reconciliation_required");Result.failure() }
        catch(_: java.io.IOException) { SyncProgress.phase(applicationContext,"retry");SyncSchedule.record(applicationContext,"network_retry_pending");Result.retry() }
        catch(_: Exception) { SyncProgress.phase(applicationContext,"error");SyncSchedule.record(applicationContext,"sync_review_required");Result.failure() }
    }
}
