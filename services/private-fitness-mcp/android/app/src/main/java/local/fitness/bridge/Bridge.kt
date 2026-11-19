package local.fitness.bridge

import android.content.Context
import android.util.AtomicFile
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.changes.DeletionChange
import androidx.health.connect.client.changes.UpsertionChange
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.*
import androidx.health.connect.client.records.metadata.DataOrigin
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.request.ChangesTokenRequest
import androidx.health.connect.client.time.TimeRangeFilter
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.Duration
import java.util.UUID
import kotlin.reflect.KClass

const val GARMIN = "com.garmin.android.apps.connectmobile"
const val ZEPP = "com.huami.watch.hmwatchmanager"

/** Android recommends a bounded reread and ID deduplication after a token expires. */
fun tokenRecoveryStart(now: Instant): Instant = now.minus(Duration.ofDays(30))
val ORIGINS = setOf(GARMIN,ZEPP)
val BASE_TYPES = setOf(HeartRateRecord::class, RestingHeartRateRecord::class,
    HeartRateVariabilityRmssdRecord::class, SleepSessionRecord::class, StepsRecord::class,
    ExerciseSessionRecord::class, WeightRecord::class, BodyFatRecord::class)
val EXTRA_TYPES = setOf(OxygenSaturationRecord::class, RespiratoryRateRecord::class,
    HeightRecord::class, LeanBodyMassRecord::class, BoneMassRecord::class, BodyWaterMassRecord::class,
    DistanceRecord::class, ActiveCaloriesBurnedRecord::class, TotalCaloriesBurnedRecord::class)
val TYPES = BASE_TYPES + EXTRA_TYPES
val READ_PERMISSIONS = TYPES.map { HealthPermission.getReadPermission(it) }.toSet()

fun array(xs: List<JSONObject>) = JSONArray().apply { xs.forEach { put(it) } }
fun obj(vararg fields: Pair<String, Any>): JSONObject = JSONObject().apply { fields.forEach { put(it.first, it.second) } }
fun batch(records: List<JSONObject>, deletions: List<JSONObject> = emptyList()) = obj(
    "schema_version" to 1, "batch_id" to UUID.randomUUID().toString(), "records" to array(records), "deletions" to array(deletions))

fun encode(r: Record): JSONObject? {
    if (r.metadata.dataOrigin.packageName !in ORIGINS) return null
    val (kind, data) = when(r) {
        is HeartRateRecord -> "heart_rate" to obj("samples" to array(r.samples.map { obj("time" to it.time.toString(), "bpm" to it.beatsPerMinute) }))
        is RestingHeartRateRecord -> "resting_heart_rate" to obj("bpm" to r.beatsPerMinute)
        is HeartRateVariabilityRmssdRecord -> "hrv_rmssd" to obj("ms" to r.heartRateVariabilityMillis)
        is StepsRecord -> "steps" to obj("count" to r.count)
        is WeightRecord -> "weight" to obj("kg" to r.weight.inKilograms)
        is BodyFatRecord -> "body_fat" to obj("percent" to r.percentage.value)
        is OxygenSaturationRecord -> "oxygen_saturation" to obj("percent" to r.percentage.value)
        is RespiratoryRateRecord -> "respiratory_rate" to obj("breaths_per_minute" to r.rate)
        is HeightRecord -> "height" to obj("cm" to (r.height.inMeters*100))
        is LeanBodyMassRecord -> "lean_body_mass" to obj("kg" to r.mass.inKilograms)
        is BoneMassRecord -> "bone_mass" to obj("kg" to r.mass.inKilograms)
        is BodyWaterMassRecord -> "body_water_mass" to obj("kg" to r.mass.inKilograms)
        is DistanceRecord -> "distance" to obj("meters" to r.distance.inMeters)
        is ActiveCaloriesBurnedRecord -> "active_calories" to obj("kcal" to r.energy.inKilocalories)
        is TotalCaloriesBurnedRecord -> "total_calories" to obj("kcal" to r.energy.inKilocalories)
        is ExerciseSessionRecord -> "activity" to obj("exercise_type" to r.exerciseType)
        is SleepSessionRecord -> "sleep" to obj("stages" to array(r.stages.map {
            val name = when(it.stage) { 1 -> "awake"; 2 -> "sleeping"; 3 -> "out_of_bed"; 4 -> "light"; 5 -> "deep"; 6 -> "rem"; 7 -> "awake_in_bed"; else -> "unknown" }
            obj("start" to it.startTime.toString(), "end" to it.endTime.toString(), "stage" to name)
        }))
        else -> return null
    }
    val (start, end) = when(r) {
        is HeartRateRecord -> r.startTime to r.endTime
        is StepsRecord -> r.startTime to r.endTime
        is SleepSessionRecord -> r.startTime to r.endTime
        is ExerciseSessionRecord -> r.startTime to r.endTime
        is RestingHeartRateRecord -> r.time to r.time
        is HeartRateVariabilityRmssdRecord -> r.time to r.time
        is WeightRecord -> r.time to r.time
        is BodyFatRecord -> r.time to r.time
        is OxygenSaturationRecord -> r.time to r.time
        is RespiratoryRateRecord -> r.time to r.time
        is HeightRecord -> r.time to r.time
        is LeanBodyMassRecord -> r.time to r.time
        is BoneMassRecord -> r.time to r.time
        is BodyWaterMassRecord -> r.time to r.time
        is DistanceRecord -> r.startTime to r.endTime
        is ActiveCaloriesBurnedRecord -> r.startTime to r.endTime
        is TotalCaloriesBurnedRecord -> r.startTime to r.endTime
        else -> return null
    }
    val units=mapOf("heart_rate" to "bpm","resting_heart_rate" to "bpm","hrv_rmssd" to "ms",
        "sleep" to "seconds","activity" to "seconds","steps" to "count","weight" to "kg","body_fat" to "percent",
        "oxygen_saturation" to "percent","respiratory_rate" to "breaths/min","height" to "cm",
        "lean_body_mass" to "kg","bone_mass" to "kg","body_water_mass" to "kg","distance" to "m",
        "active_calories" to "kcal","total_calories" to "kcal")
    fun optionalGetter(target:Any,name:String):Any = try {
        target.javaClass.methods.firstOrNull { it.name==name && it.parameterCount==0 }?.invoke(target) ?: JSONObject.NULL
    } catch(_:Exception) { JSONObject.NULL }
    fun offset(name:String):Any {
        val value=optionalGetter(r,name)
        return if(value==JSONObject.NULL) JSONObject.NULL else value.toString()
    }
    val device=r.metadata.device
    val deviceInfo=if(device==null) JSONObject.NULL else obj("manufacturer" to (device.manufacturer ?: JSONObject.NULL),
        "model" to (device.model ?: JSONObject.NULL),"type" to device.type,
        "identifier" to optionalGetter(device,"getIdentifier"))
    data.put("_provenance",obj("source_app" to r.metadata.dataOrigin.packageName,
        "device" to deviceInfo,"client_record_id" to (r.metadata.clientRecordId ?: JSONObject.NULL),
        "client_record_version" to r.metadata.clientRecordVersion,"recording_method" to r.metadata.recordingMethod,
        "original_start" to start.toString(),"original_end" to end.toString(),
        "start_zone_offset" to offset("getStartZoneOffset"),
        "end_zone_offset" to offset("getEndZoneOffset"),
        "zone_offset" to offset("getZoneOffset"),"unit" to units.getValue(kind),
        "unit_basis" to "Health Connect SDK normalized unit; source display unit unavailable"))
    return obj("origin" to r.metadata.dataOrigin.packageName, "record_id" to r.metadata.id, "kind" to kind,
        "start" to start.toString(), "end" to end.toString(), "modified" to r.metadata.lastModifiedTime.toString(), "data" to data)
}

class Bridge(private val context: Context, val origin:String=GARMIN,
    private val recordTypes:Set<KClass<out Record>> = BASE_TYPES,
    private val streamKey:String="sync",pendingName:String="outbox.json") {
    private val client = HealthConnectClient.getOrCreate(context)
    private val prefs = context.getSharedPreferences(streamKey, Context.MODE_PRIVATE)
    private val pending = AtomicFile(java.io.File(context.filesDir, pendingName))
    private val checkpointFile = AtomicFile(java.io.File(context.filesDir, pendingName+".progress"))
    private suspend fun grantedTypes(): Set<KClass<out Record>> {
        val grants = client.permissionController.getGrantedPermissions()
        return recordTypes.filter { HealthPermission.getReadPermission(it) in grants }.toSet()
    }
    private suspend fun <T: Record> snapshot(type: KClass<T>, start: Instant, end: Instant): List<JSONObject> {
        val out = mutableListOf<JSONObject>(); var page: String? = null
        do {
            val response = client.readRecords(ReadRecordsRequest(type, TimeRangeFilter.between(start,end),
                dataOriginFilter = setOf(DataOrigin(origin)), pageSize = 1000, pageToken = page))
            SyncProgress.phase(context,"reading")
            out.addAll(response.records.mapNotNull { encode(it) }); page = response.pageToken
        } while (!page.isNullOrEmpty())
        return out
    }
    // One caller at a time: UI disables overlapping runs; worker uses unique work.
    // Durable outbox persists before send. Cursor commits only after every batch has an ACK.
    suspend fun prepare(): JSONObject {
        val types = grantedTypes()
        val typeKey = types.map { it.simpleName }.sortedBy { it }.joinToString(",")
        if(types.isEmpty()) return obj("skipped" to true)
        if (pending.baseFile.exists() || java.io.File(pending.baseFile.path+".bak").exists()) {
            val saved = JSONObject(pending.openRead().bufferedReader().use { it.readText() })
            require(saved.getString("types") == typeKey) { "Permissions changed; pending data will not upload" }
            return saved
        }
        val previousKey = prefs.getString("types", null)
        require(previousKey == null || previousKey == typeKey) { "Permission set changed; reconcile database before resetting sync" }
        var token = prefs.getString("cursor", null)
        val records = mutableListOf<JSONObject>(); val deletions = mutableListOf<JSONObject>()
        if (token == null) {
            // Obtain cursor before snapshot so concurrent changes are replayed safely.
            token = client.getChangesToken(ChangesTokenRequest(types, setOf(DataOrigin(origin))))
            val end = Instant.now(); val start = end.minus(Duration.ofDays(7))
            for (type in types) records.addAll(snapshot(type,start,end))
        } else {
            do {
                val response = client.getChanges(token!!)
                SyncProgress.phase(context,"reading")
                if (response.changesTokenExpired) {
                    // The old token no longer contains a reliable deletion history.
                    // Reserve the replacement token before the bounded snapshot so
                    // concurrent edits are replayed on a subsequent sync.
                    token = client.getChangesToken(ChangesTokenRequest(types, setOf(DataOrigin(origin))))
                    records.clear(); deletions.clear()
                    SyncSchedule.noteUnverifiedDeletions(context, streamKey)
                    val recoveryEnd = Instant.now()
                    val recoveryStart = tokenRecoveryStart(recoveryEnd)
                    for (type in types) records.addAll(snapshot(type, recoveryStart, recoveryEnd))
                    // Upserts dedupe by source/record identity and revision server-side.
                    // Missing deletion events cannot be inferred from this snapshot.
                    break
                }
                for (change in response.changes) when(change) {
                    is UpsertionChange -> encode(change.record)?.let { records.add(it) }
                    is DeletionChange -> deletions.add(obj("origin" to origin, "record_id" to change.recordId, "modified" to Instant.now().toString()))
                }
                token = response.nextChangesToken
            } while(response.hasMore)
        }
        val batches = mutableListOf<JSONObject>()
        records.chunked(10).forEach { batches.addAll(splitBatch(batch(it))) }
        deletions.chunked(100).forEach { batches.addAll(splitBatch(batch(emptyList(),it))) }
        // Persist empty batches too: cursor advances safely even when no measurements exist.
        if (batches.isEmpty()) batches.add(batch(emptyList()))
        val envelope = obj("source_app" to origin,"next_cursor" to token!!, "types" to typeKey, "batches" to array(batches))
        persist(envelope)
        return envelope
    }
    private fun persist(envelope:JSONObject,target:AtomicFile=pending) {
        val stream=target.startWrite()
        try {
            stream.write(envelope.toString().toByteArray(Charsets.UTF_8))
            target.finishWrite(stream)
        } catch(e:Exception) { target.failWrite(stream);throw e }
    }
    suspend fun prepareUpload(background:Boolean):JSONObject {
        var envelope=prepare()
        if(!envelope.optBoolean("skipped",false)) {
            if(checkpointFile.baseFile.exists() || java.io.File(checkpointFile.baseFile.path+".bak").exists()) {
                val saved=JSONObject(checkpointFile.openRead().bufferedReader().use { it.readText() })
                if(saved.getString("first_batch_id")==envelope.getJSONArray("batches").getJSONObject(0).getString("batch_id"))
                    envelope.put("next_batch",saved.getInt("next_batch"))
            }
            envelope=repairUpload(envelope) { persist(it) }
            val before=envelope.toString()
            initializeUpload(envelope,background)
            // Persist the stable completion ID before any network request.
            if(envelope.toString()!=before)persist(envelope)
        }
        return envelope
    }
    fun checkpoint(envelope:JSONObject,next:Int) {
        checkpointUpload(envelope,next) {
            // Keep each durable write small even for a large historical queue.
            persist(obj("first_batch_id" to it.getJSONArray("batches").getJSONObject(0).getString("batch_id"),
                "next_batch" to next),checkpointFile)
        }
    }
    fun acknowledge(envelope: JSONObject) {
        check(prefs.edit().putString("cursor",envelope.getString("next_cursor")).putString("types",envelope.getString("types")).commit())
        pending.delete()
        check(!pending.baseFile.exists()) { "Cannot clear acknowledged outbox" }
        checkpointFile.delete()
    }
}

// Legacy Garmin cursor and outbox are retained exactly. Added sources and record
// types get independent cursors: permission additions cannot reset Garmin history.
fun sourceStreams(context:Context):List<Bridge> {
    val streams=mutableListOf(Bridge(context))
    for(origin in ORIGINS) for(type in TYPES) {
        if(origin==GARMIN && type in BASE_TYPES)continue
        val key="source-v1-"+origin+"-"+type.simpleName
        streams.add(Bridge(context,origin,setOf(type),key,key+".json"))
    }
    return streams
}
