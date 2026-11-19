package local.fitness.bridge

import androidx.health.connect.client.records.*
import androidx.health.connect.client.records.metadata.DataOrigin
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Percentage
import java.time.Instant
import java.time.ZoneOffset
import org.junit.Assert.*
import org.junit.Test

class SourceEncodingTest {
    private fun metadata(origin:String):Metadata {
        val constructor=Metadata::class.java.getDeclaredConstructor(Int::class.javaPrimitiveType,
            String::class.java,DataOrigin::class.java,Instant::class.java,String::class.java,
            Long::class.javaPrimitiveType,Device::class.java)
        constructor.isAccessible=true
        return constructor.newInstance(Metadata.RECORDING_METHOD_AUTOMATICALLY_RECORDED,"shared-id",
            DataOrigin(origin),Instant.parse("2020-10-18T12:01:00Z"),"client-id",1L,
            Device(type=Device.TYPE_WATCH,manufacturer="Synthetic",model="Test"))
    }
    @Test fun zeppAndGarminKeepTheirOwnIdentityAndUnits() {
        val time=Instant.parse("2020-10-18T12:00:00Z")
        for(origin in listOf(GARMIN,ZEPP)) {
            val value=encode(OxygenSaturationRecord(time,ZoneOffset.ofHours(-5),Percentage(97.0),metadata(origin)))!!
            assertEquals(origin,value.getString("origin"))
            assertEquals("shared-id",value.getString("record_id"))
            val provenance=value.getJSONObject("data").getJSONObject("_provenance")
            assertEquals("percent",provenance.getString("unit"))
            assertEquals("-05:00",provenance.getString("zone_offset"))
            assertEquals("Test",provenance.getJSONObject("device").getString("model"))
            assertTrue(provenance.getJSONObject("device").isNull("identifier"))
        }
    }
    @Test fun breathingIsPreservedAndUnknownSourceIsExcluded() {
        val time=Instant.parse("2020-10-18T12:00:00Z")
        val r=encode(RespiratoryRateRecord(time,null,14.0,metadata(ZEPP)))!!
        assertEquals("respiratory_rate",r.getString("kind"))
        assertEquals(14.0,r.getJSONObject("data").getDouble("breaths_per_minute"),0.001)
        assertNull(encode(RespiratoryRateRecord(time,null,14.0,metadata("other.app"))))
    }
    @Test fun originalGarminTypesStayIndependentOfNewPermissions() {
        assertEquals(8,BASE_TYPES.size)
        assertFalse(OxygenSaturationRecord::class in BASE_TYPES)
        assertTrue(OxygenSaturationRecord::class in TYPES)
    }
}
