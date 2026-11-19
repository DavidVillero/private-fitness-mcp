package local.fitness.bridge

import org.junit.Assert.*
import org.junit.Test

class ProgressStateTest {
    @Test fun readingShowsIndeterminateActivity() {
        val p=progressViewState("reading",0,0,1000,1001)
        assertTrue(p.active);assertTrue(p.indeterminate);assertTrue(p.visible)
    }
    @Test fun allBatchesSentIsNotYetCommittedSuccess() {
        val p=progressViewState("uploading",10,10,1000,1001)
        assertEquals(99,p.percent)
        assertTrue(p.active)
        assertEquals(99,progressViewState("committing",10,10,1000,1001).percent)
        assertEquals(100,progressViewState("complete",10,10,1000,1001).percent)
    }
    @Test fun knownBatchesHaveBoundedProgress() {
        assertEquals(25,progressViewState("uploading",1,4,1000,1001).percent)
        assertEquals(99,progressViewState("uploading",100,4,1000,1001).percent)
        assertEquals(0,progressViewState("uploading",-1,4,1000,1001).percent)
    }
    @Test fun largeCountsCannotOverflowProgress() {
        assertEquals(99,progressViewState("uploading",Int.MAX_VALUE,1,1000,1001).percent)
    }
    @Test fun unknownTotalCannotDivideByZero() {
        assertTrue(progressViewState("uploading",0,0,1000,1001).indeterminate)
    }
    @Test fun interruptedProcessDoesNotShowAnEndlessActiveBar() {
        val p=progressViewState("uploading",3,10,1000,122000)
        assertFalse(p.active);assertFalse(p.indeterminate)
        assertTrue(p.label.contains("resume"));assertEquals(30,p.percent)
    }
    @Test fun retryKeepsAcknowledgedProgressWithoutClaimingCompletion() {
        val p=progressViewState("retry",2,8,1000,1001)
        assertEquals(25,p.percent);assertFalse(p.active);assertTrue(p.label.contains("retry"))
    }
}
