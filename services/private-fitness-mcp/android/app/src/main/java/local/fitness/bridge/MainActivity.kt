package local.fitness.bridge

import android.content.SharedPreferences
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.*
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.metadata.DataOrigin
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Phone-owned sync controls. Measurement values remain in Health Connect and on the Mac. */
class MainActivity : ComponentActivity() {
    private val ink = Color.rgb(29, 53, 43)
    private val muted = Color.rgb(91, 110, 100)
    private val paper = Color.rgb(246, 247, 241)
    private val lime = Color.rgb(220, 241, 158)
    private val line = Color.rgb(222, 229, 217)
    private val white = Color.WHITE
    private lateinit var status: TextView
    private lateinit var progressBar: ProgressBar
    private lateinit var progressLabel: TextView
    private lateinit var heroTitle: TextView
    private lateinit var lastSyncLabel: TextView
    private lateinit var syncNowButton: Button
    private lateinit var hourlySwitch: Switch
    private lateinit var scheduleLabel: TextView
    private lateinit var accessLabel: TextView
    private lateinit var pairingLabel: TextView
    private lateinit var setupButton: Button
    private lateinit var overview: ScrollView
    private lateinit var settings: ScrollView
    private lateinit var overviewTab: Button
    private lateinit var settingsTab: Button
    private var busy = false
    private var paired = false
    private var healthReady = false
    private var backgroundReady = false
    private var updatingSwitch = false
    private var exportText: String? = null
    private var enableAfterPermission = false
    private var selectedPage = 0
    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() { renderProgress(); handler.postDelayed(this, 1000) }
    }
    private val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, _ ->
        runOnUiThread { renderProgress() }
    }
    private val permissions = registerForActivityResult(PermissionController.createRequestPermissionResultContract()) {
        lifecycleScope.launch {
            refreshAccess()
            if (enableAfterPermission) {
                enableAfterPermission = false
                if (backgroundReady && healthReady && paired) {
                    SyncSchedule.enable(this@MainActivity)
                    showMessage("Automatic sync is on. Your data will sync in the background.")
                } else showMessage("Allow background health access to use automatic sync.")
            } else showMessage(if (healthReady) "Health access updated." else "Allow at least one health category to start syncing.")
            renderProgress()
        }
    }
    private val save = registerForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        try {
            if (uri != null && exportText != null) {
                contentResolver.openOutputStream(uri)?.bufferedWriter()?.use { it.write(exportText!!) }
                showMessage("Diagnostic export saved to the location you chose.")
            }
        } catch (_: Exception) { showMessage("Could not save the export. Please try another location.") }
        exportText = null
    }

    private fun dp(n: Int) = (n * resources.displayMetrics.density).toInt()
    private fun shape(color: Int, radius: Int = 24, border: Int? = null) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(radius).toFloat()
        if (border != null) setStroke(dp(1), border)
    }
    private fun text(value: String, size: Float = 15f, color: Int = ink, bold: Boolean = false) = TextView(this).apply {
        text = value; textSize = size; setTextColor(color)
        typeface = Typeface.create("sans-serif", if (bold) Typeface.BOLD else Typeface.NORMAL)
        setLineSpacing(dp(3).toFloat(), 1f)
    }
    private fun LinearLayout.gap(height: Int = 12) { addView(View(this@MainActivity), LinearLayout.LayoutParams(1, dp(height))) }
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun card(color: Int = white, border: Int? = line) = column().apply {
        background = shape(color, 24, border); setPadding(dp(22), dp(22), dp(22), dp(22))
        layoutParams = LinearLayout.LayoutParams(-1, -2)
    }
    private fun button(label: String, filled: Boolean = false, action: () -> Unit) = Button(this).apply {
        text = label; textSize = 15f; isAllCaps = false
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setTextColor(ink); background = shape(if (filled) lime else paper, 16)
        minHeight = dp(52); minimumHeight = dp(52); setPadding(dp(18), dp(12), dp(18), dp(12))
        stateListAnimator = null
        layoutParams = LinearLayout.LayoutParams(-1, -2)
        setOnClickListener { action() }
    }
    private fun showMessage(message: String) { status.text = message; status.visibility = View.VISIBLE }
    private fun selectPage(page: Int) {
        selectedPage = page
        overview.visibility = if (page == 0) View.VISIBLE else View.GONE
        settings.visibility = if (page == 1) View.VISIBLE else View.GONE
        overviewTab.background = shape(if (page == 0) ink else Color.TRANSPARENT, 16)
        settingsTab.background = shape(if (page == 1) ink else Color.TRANSPARENT, 16)
        overviewTab.setTextColor(if (page == 0) white else muted)
        settingsTab.setTextColor(if (page == 1) white else muted)
        overviewTab.isSelected = page == 0; settingsTab.isSelected = page == 1
    }
    private fun scroll(content: LinearLayout) = ScrollView(this).apply {
        isFillViewport = false; clipToPadding = false
        setPadding(dp(22), dp(12), dp(22), dp(22)); addView(content)
    }
    private fun openTailscale() {
        val intent = packageManager.getLaunchIntentForPackage("com.tailscale.ipn")
        if (intent != null) startActivity(intent)
        else showMessage("Install Tailscale and connect to your private network first.")
    }
    private suspend fun refreshAccess() {
        paired = try { Vault(this).endpoint(); Vault(this).token().isNotBlank() } catch (_: Exception) { false }
        val available = HealthConnectClient.getSdkStatus(this) == HealthConnectClient.SDK_AVAILABLE
        val grants = if (available) try {
            HealthConnectClient.getOrCreate(this).permissionController.getGrantedPermissions()
        } catch (_: Exception) { emptySet() } else emptySet()
        healthReady = READ_PERMISSIONS.any { it in grants }
        backgroundReady = HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND in grants
        pairingLabel.text = if (paired) "Mac pairing saved" else "Mac pairing needed"
        accessLabel.text = if (!available) "Health Connect unavailable" else if (healthReady) "Health read access ready" else "Health read access needed"
        setupButton.visibility = if (paired && healthReady) View.GONE else View.VISIBLE
        if (paired && healthReady && backgroundReady && getSharedPreferences("sync-status", MODE_PRIVATE).getBoolean("enabled", false)) {
            SyncSchedule.ensurePeriodic(this)
        }
        renderProgress()
    }
    private fun renderProgress() {
        if (!::progressBar.isInitialized) return
        val view = SyncProgress.view(this)
        val prefs = getSharedPreferences("sync-status", MODE_PRIVATE)
        val p = getSharedPreferences("sync-progress", MODE_PRIVATE)
        val phase = p.getString("phase", "idle") ?: "idle"
        val source = p.getString("source", null)
        heroTitle.text = when {
            !paired || !healthReady -> "Let’s get connected."
            view.active -> "Bringing it all together."
            phase == "retry" -> "We’ll try again."
            phase == "error" -> "A little help needed."
            phase == "complete" -> "You’re up to date."
            else -> "Ready when you are."
        }
        progressLabel.text = when {
            !paired -> "Pair this phone with your Mac to start syncing."
            !healthReady -> "Choose the health data you’d like to sync."
            else -> (if (source != null && view.active) "$source · " else "") + view.label
        }
        progressBar.visibility = if (view.visible && paired && healthReady) View.VISIBLE else View.GONE
        progressBar.isIndeterminate = view.indeterminate
        if (!view.indeterminate) progressBar.progress = view.percent
        val last = prefs.getString("last_success", null)
        lastSyncLabel.text = "LAST COMPLETED SYNC\n" + try {
            if (last == null) "No completed sync yet" else DateTimeFormatter.ofPattern("MMM d · h:mm a").withZone(ZoneId.systemDefault()).format(Instant.parse(last))
        } catch (_: Exception) { "No completed sync yet" }
        syncNowButton.isEnabled = !busy && !view.active && paired && healthReady
        syncNowButton.alpha = if (syncNowButton.isEnabled) 1f else 0.55f
        syncNowButton.text = if (view.active || busy) "Sync in progress…" else "Sync now"
        val enabled = prefs.getBoolean("enabled", false)
        updatingSwitch = true; hourlySwitch.isChecked = enabled; updatingSwitch = false
        hourlySwitch.isEnabled = !busy
        scheduleLabel.text = when {
            !enabled -> "Off · Sync manually whenever you like."
            !backgroundReady -> "Needs background health access."
            else -> "On · About once an hour, when Android allows."
        }
    }
    private fun runTask(sync: Boolean = false, block: suspend () -> Unit) {
        if (busy) return
        busy = true
        if (sync) { selectPage(0); overview.smoothScrollTo(0, 0) }
        renderProgress()
        lifecycleScope.launch {
            try { block() }
            catch (e: CancellationException) { throw e }
            catch (_: java.io.IOException) {
                if (sync) SyncProgress.phase(this@MainActivity, "retry")
                showMessage("Your data is saved. Check Tailscale and keep your Mac online, then try again.")
            }
            catch (_: OversizedRecordException) {
                if (sync) SyncProgress.phase(this@MainActivity, "oversized")
                showMessage("A source record exceeds the upload limit. Your data is retained. See the oversized-record recovery instructions before retrying.")
            }
            catch (_: Exception) {
                if (sync) SyncProgress.phase(this@MainActivity, "error")
                showMessage("Check health permissions and Mac pairing in Settings, then try again. Your queued data is saved.")
            }
            finally { busy = false; renderProgress() }
        }
    }
    private fun enableHourly() = runTask {
        refreshAccess()
        if (!paired || !healthReady) {
            selectPage(1); showMessage("Finish health access and Mac pairing before enabling automatic sync.")
        } else if (!backgroundReady) {
            val client = HealthConnectClient.getOrCreate(this@MainActivity)
            if (client.features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND) == HealthConnectFeatures.FEATURE_STATUS_AVAILABLE) {
                enableAfterPermission = true
                permissions.launch(setOf(HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND))
            } else showMessage("This phone doesn’t support background health access. Use Sync now instead.")
        } else {
            SyncSchedule.enable(this@MainActivity)
            showMessage("Automatic sync is on. Keep Tailscale connected and your Mac online.")
        }
    }
    private fun requestHealthAccess(background: Boolean = false) {
        if (HealthConnectClient.getSdkStatus(this) != HealthConnectClient.SDK_AVAILABLE) {
            showMessage("Health Connect isn’t available. Update it in your phone’s settings first."); return
        }
        val client = HealthConnectClient.getOrCreate(this)
        if (background && client.features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND) != HealthConnectFeatures.FEATURE_STATUS_AVAILABLE) {
            showMessage("This permission isn’t supported on this phone."); return
        }
        permissions.launch(when {
            background -> setOf(HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND)
            else -> READ_PERMISSIONS
        })
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = column().apply { setBackgroundColor(paper) }
        root.setOnApplyWindowInsetsListener { v, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom); insets
        }
        val brand = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL; setPadding(dp(24), dp(14), dp(24), dp(14))
        }
        brand.addView(text("pf", 20f, lime, true).apply {
            gravity = Gravity.CENTER; background = shape(ink, 14)
        }, LinearLayout.LayoutParams(dp(44), dp(44)))
        brand.addView(text("  private fitness", 20f, ink, true), LinearLayout.LayoutParams(0, -2, 1f))
        brand.addView(text("YOUR DATA. YOURS.", 9f, muted, true))
        root.addView(brand)
        status = text("", 14f, ink).apply {
            visibility = View.GONE; background = shape(lime, 16)
            setPadding(dp(16), dp(12), dp(16), dp(12))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        root.addView(status, LinearLayout.LayoutParams(-1, -2).apply {
            setMargins(dp(22), 0, dp(22), dp(8))
        })

        val home = column()
        home.addView(text("A little more connected.", 13f, muted))
        home.gap(4)
        home.addView(text("Your health,\nin sync.", 36f, ink, true))
        home.gap(20)
        val hero = card(ink, null)
        hero.addView(text("●  PRIVATE SYNC", 11f, lime, true))
        hero.gap(16)
        heroTitle = text("Ready when you are.", 25f, white, true); hero.addView(heroTitle)
        hero.gap(8)
        progressLabel = text("Checking your connection…", 14f, Color.rgb(213, 225, 217)); hero.addView(progressLabel)
        hero.gap(16)
        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100; progressTintList = ColorStateList.valueOf(lime)
            progressBackgroundTintList = ColorStateList.valueOf(Color.rgb(76, 101, 87))
            indeterminateTintList = ColorStateList.valueOf(lime)
            contentDescription = "Upload progress"
        }
        hero.addView(progressBar, LinearLayout.LayoutParams(-1, dp(6)))
        hero.gap(16)
        lastSyncLabel = text("", 12f, Color.rgb(213, 225, 217)); hero.addView(lastSyncLabel)
        hero.gap(20)
        syncNowButton = button("Sync now", true) {
            runTask(sync = true) {
                withContext(Dispatchers.IO) { upload(applicationContext) }
                SyncSchedule.record(this@MainActivity, "ok", success = true)
                showMessage("All queued batches were acknowledged by your Mac.")
            }
        }
        hero.addView(syncNowButton); home.addView(hero)
        home.gap(14)
        val automatic = card()
        val row = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        row.addView(text("Automatic sync", 18f, ink, true), LinearLayout.LayoutParams(0, -2, 1f))
        hourlySwitch = Switch(this).apply {
            contentDescription = "Automatic hourly sync"
            thumbTintList = ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(ink, muted))
            trackTintList = ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(lime, line))
            minHeight = dp(48); minWidth = dp(52)
            setOnCheckedChangeListener { _, checked ->
                if (!updatingSwitch) {
                    if (checked) enableHourly()
                    else { SyncSchedule.disable(this@MainActivity); showMessage("Automatic sync paused. You can still use Sync now."); renderProgress() }
                }
            }
        }
        row.addView(hourlySwitch); automatic.addView(row)
        scheduleLabel = text("", 14f, muted); automatic.addView(scheduleLabel)
        home.addView(automatic); home.gap(14)
        val connections = card()
        connections.addView(text("Your connections", 18f, ink, true)); connections.gap(14)
        accessLabel = text("Checking health access…", 15f); connections.addView(accessLabel)
        connections.addView(text("Garmin + Zepp through Health Connect", 12f, muted)); connections.gap(14)
        pairingLabel = text("Checking Mac pairing…", 15f); connections.addView(pairingLabel)
        connections.addView(text("Keep your Mac online and Tailscale connected.", 12f, muted)); connections.gap(16)
        setupButton = button("Finish setup") { selectPage(1) }; connections.addView(setupButton)
        connections.addView(button("Manage connections") { selectPage(1) })
        home.addView(connections); home.gap(20)
        home.addView(text("Only your phone. Only your Mac.\nNo ads or analytics. Health access is read-only.", 12f, muted).apply { gravity = Gravity.CENTER })
        overview = scroll(home)

        val config = column()
        config.addView(text("Make it work for you.", 13f, muted)); config.gap(4)
        config.addView(text("Settings", 34f, ink, true)); config.gap(20)
        val access = card()
        access.addView(text("Health access", 20f, ink, true)); access.gap(6)
        access.addView(text("Choose which health categories this phone can read. We never change your health records.", 14f, muted)); access.gap(16)
        access.addView(button("Manage health permissions", true) { requestHealthAccess() }); access.gap(8)
        access.addView(button("Allow background health access") { requestHealthAccess(background = true) }); access.gap(8)
        access.addView(text("The initial import covers seven days. Extended permission alone doesn’t expand that import.", 12f, muted))
        config.addView(access); config.gap(14)
        val network = card()
        network.addView(text("Private Mac connection", 20f, ink, true)); network.gap(6)
        network.addView(text("Tailscale securely connects this phone to your Mac. Open it if syncing is waiting for a connection.", 14f, muted)); network.gap(16)
        network.addView(button("Open Tailscale", true) { openTailscale() }); network.gap(8)
        network.addView(button("Check setup again") { runTask { refreshAccess(); showMessage(if (paired && healthReady) "Pairing and health access are ready. Try Sync now to check the connection." else "Mac pairing or health access is still needed.") } })
        network.gap(12)
        val advanced = column().apply { visibility = View.GONE }
        network.addView(button("Advanced pairing") { advanced.visibility = if (advanced.visibility == View.VISIBLE) View.GONE else View.VISIBLE })
        advanced.gap(12)
        advanced.addView(text("Pairing is usually restored securely from your Mac over USB. Enter a connection manually only if needed.", 13f, muted)); advanced.gap(12)
        advanced.addView(text("Private HTTPS address", 13f, ink, true))
        val endpoint = EditText(this).apply {
            hint = "https://your-mac:8443/v1/ingest"; textSize = 14f; setTextColor(ink)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO; minHeight = dp(52)
            contentDescription = "Private HTTPS address"
        }
        advanced.addView(endpoint)
        advanced.addView(text("Pairing token", 13f, ink, true))
        val token = EditText(this).apply {
            hint = "Enter the token from your Mac"; textSize = 14f; setTextColor(ink)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO; minHeight = dp(52)
            contentDescription = "Pairing token"
        }
        advanced.addView(token); advanced.gap(8)
        advanced.addView(button("Save connection") {
            try {
                Vault(this).save(endpoint.text.toString().trim(), token.text.toString().trim()); token.text.clear()
                runTask { refreshAccess(); showMessage("Mac pairing saved securely. Try Sync now.") }
            } catch (_: Exception) { showMessage("Use an HTTPS address ending in /v1/ingest and a token of at least 32 characters.") }
        })
        network.addView(advanced); config.addView(network); config.gap(14)
        val privacy = card()
        privacy.addView(text("Private by design", 20f, ink, true)); privacy.gap(8)
        privacy.addView(text("The bridge reads Garmin and Zepp records in Health Connect and sends them only to your paired Mac. No ads, analytics, or public upload service. Revoke read access at any time in Health Connect. Data shared with an AI provider depends on the tools you choose to use.", 14f, muted))
        config.addView(privacy); config.gap(14)
        val diagnostics = card()
        diagnostics.addView(text("Help & diagnostics", 20f, ink, true)); diagnostics.gap(8)
        diagnostics.addView(text("If syncing pauses, check Tailscale, health access, and that your Mac is awake. Large queues resume from the last saved batch.", 14f, muted)); diagnostics.gap(12)
        diagnostics.addView(button("Export a Garmin test record") {
            runTask {
                exportText = withContext(Dispatchers.IO) {
                    val client = HealthConnectClient.getOrCreate(this@MainActivity)
                    val end = Instant.now(); var page: String? = null; var found: HeartRateRecord? = null
                    do {
                        val response = client.readRecords(ReadRecordsRequest(HeartRateRecord::class, TimeRangeFilter.between(end.minus(Duration.ofDays(7)), end), dataOriginFilter = setOf(DataOrigin(GARMIN)), pageSize = 100, pageToken = page))
                        val candidate = response.records.maxByOrNull { it.endTime }
                        if (candidate != null && (found == null || candidate.endTime > found!!.endTime)) found = candidate
                        page = response.pageToken
                    } while (!page.isNullOrEmpty())
                    check(found != null); batch(listOf(encode(found!!)!!)).toString(2)
                }
                save.launch("garmin-first-record.json")
            }
        })
        diagnostics.gap(8); diagnostics.addView(text("Exports contain personal health data. Save them only to a location you trust.", 12f, muted))
        config.addView(diagnostics); config.gap(20)
        config.addView(text("PRIVATE FITNESS  ·  0.6.0", 11f, muted, true).apply { gravity = Gravity.CENTER })
        settings = scroll(config)
        val pages = FrameLayout(this).apply { addView(overview); addView(settings) }
        root.addView(pages, LinearLayout.LayoutParams(-1, 0, 1f))
        val nav = LinearLayout(this).apply {
            setPadding(dp(22), dp(10), dp(22), dp(12)); gravity = Gravity.CENTER
            background = shape(paper, 0)
        }
        overviewTab = button("Overview") { selectPage(0) }
        settingsTab = button("Settings") { selectPage(1) }
        nav.addView(overviewTab, LinearLayout.LayoutParams(0, dp(52), 1f).apply { marginEnd = dp(8) })
        nav.addView(settingsTab, LinearLayout.LayoutParams(0, dp(52), 1f))
        root.addView(nav)
        setContentView(root); root.requestApplyInsets()
        val lightBars = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
        window.insetsController?.setSystemBarsAppearance(lightBars, lightBars)
        selectPage(savedInstanceState?.getInt("page", 0) ?: 0)
        try {
            if (Vault(this).importUsbPairing()) showMessage("This phone is now paired with your Mac. You’re ready to set up sync.")
        } catch (_: Exception) { showMessage("Mac pairing couldn’t be restored. Reconnect this phone to your Mac for setup.") }
    }
    override fun onStart() {
        super.onStart()
        getSharedPreferences("sync-progress", MODE_PRIVATE).registerOnSharedPreferenceChangeListener(listener)
        getSharedPreferences("sync-status", MODE_PRIVATE).registerOnSharedPreferenceChangeListener(listener)
        lifecycleScope.launch { refreshAccess() }
        handler.post(refresh)
    }
    override fun onStop() {
        handler.removeCallbacks(refresh)
        getSharedPreferences("sync-progress", MODE_PRIVATE).unregisterOnSharedPreferenceChangeListener(listener)
        getSharedPreferences("sync-status", MODE_PRIVATE).unregisterOnSharedPreferenceChangeListener(listener)
        super.onStop()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt("page", selectedPage); super.onSaveInstanceState(outState)
    }
}
