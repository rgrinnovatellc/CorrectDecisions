package org.lostboundaries.probe;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Process;
import android.os.SystemClock;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

public final class ProbeReceiver extends BroadcastReceiver {
    private static final String ACTION = "org.lostboundaries.probe.COMMAND";
    private static final int JOB_ID = 17001;
    private static final long MIN_LATENCY_MS = 15 * 60 * 1000L;

    @Override
    public void onReceive(Context context, Intent intent) {
        JSONObject result = new JSONObject();
        boolean success = false;
        try {
            if (intent == null || !ACTION.equals(intent.getAction())) {
                throw new IllegalArgumentException("unexpected action");
            }
            String command = intent.getStringExtra("cmd");
            put(result, "schema", 1);
            put(result, "command", command);
            put(result, "uid", Process.myUid());
            put(result, "process_entry_elapsed_ms", SystemClock.elapsedRealtime());
            JobScheduler scheduler = context.getSystemService(JobScheduler.class);
            if ("schedule".equals(command)) {
                scheduler.cancel(JOB_ID);
                context.getSharedPreferences(HoldJobService.PREFS, Context.MODE_PRIVATE)
                        .edit().putInt(HoldJobService.CALLBACKS, 0).commit();
                JobInfo job = new JobInfo.Builder(
                        JOB_ID, new ComponentName(context, HoldJobService.class))
                        .setMinimumLatency(MIN_LATENCY_MS)
                        .setRequiresDeviceIdle(true)
                        .build();
                long before = SystemClock.elapsedRealtime();
                int scheduleResult = scheduler.schedule(job);
                long after = SystemClock.elapsedRealtime();
                put(result, "schedule_before_elapsed_ms", before);
                put(result, "schedule_after_elapsed_ms", after);
                put(result, "schedule_result", scheduleResult);
                put(result, "job_id", JOB_ID);
                put(result, "minimum_latency_ms", MIN_LATENCY_MS);
                put(result, "requires_device_idle", true);
                put(result, "requires_charging", false);
                put(result, "requires_battery_not_low", false);
                put(result, "persisted", false);
                success = scheduleResult == JobScheduler.RESULT_SUCCESS;
            } else if ("query".equals(command)) {
                long before = SystemClock.elapsedRealtime();
                Map<Integer, Duration> stats = scheduler.getPendingJobReasonStats(JOB_ID);
                long after = SystemClock.elapsedRealtime();
                put(result, "query_before_elapsed_ms", before);
                put(result, "query_after_elapsed_ms", after);
                putStats(result, stats);
                success = scheduler.getPendingJob(JOB_ID) != null;
            } else if ("cancel".equals(command)) {
                scheduler.cancel(JOB_ID);
                success = scheduler.getPendingJob(JOB_ID) == null;
            } else {
                throw new IllegalArgumentException("cmd must be schedule, query, or cancel");
            }
            put(result, "pending", scheduler.getPendingJob(JOB_ID) != null);
            put(result, "callback_count",
                    context.getSharedPreferences(HoldJobService.PREFS, Context.MODE_PRIVATE)
                            .getInt(HoldJobService.CALLBACKS, 0));
            put(result, "success", success);
        } catch (Throwable error) {
            success = false;
            put(result, "success", false);
            put(result, "error", error.getClass().getName() + ": " + error.getMessage());
        }
        String encoded = Base64.encodeToString(
                result.toString().getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
        setResultCode(success ? -1 : 0);
        setResultData("LB64:" + encoded);
    }

    private static void putStats(JSONObject result, Map<Integer, Duration> stats) {
        JSONObject values = new JSONObject();
        JSONObject names = new JSONObject();
        List<Integer> codes = new ArrayList<>(stats.keySet());
        Collections.sort(codes);
        long maximum = Long.MIN_VALUE;
        JSONArray maximumCodes = new JSONArray();
        for (int code : codes) {
            long millis = stats.get(code).toMillis();
            put(values, Integer.toString(code), millis);
            put(names, Integer.toString(code), reasonName(code));
            if (millis > maximum) {
                maximum = millis;
                maximumCodes = new JSONArray();
                maximumCodes.put(code);
            } else if (millis == maximum) {
                maximumCodes.put(code);
            }
        }
        put(result, "stats_ms", values);
        put(result, "reason_names", names);
        put(result, "max_duration_ms", maximum == Long.MIN_VALUE ? 0 : maximum);
        put(result, "max_codes", maximumCodes);
        put(result, "unique_argmax", maximumCodes.length() == 1);
        if (maximumCodes.length() == 1) {
            int code = maximumCodes.optInt(0);
            put(result, "argmax_code", code);
            put(result, "argmax_name", reasonName(code));
        }
    }

    private static String reasonName(int code) {
        if (code == JobScheduler.PENDING_JOB_REASON_APP_STANDBY) {
            return "APP_STANDBY";
        }
        if (code == JobScheduler.PENDING_JOB_REASON_CONSTRAINT_MINIMUM_LATENCY) {
            return "CONSTRAINT_MINIMUM_LATENCY";
        }
        if (code == JobScheduler.PENDING_JOB_REASON_CONSTRAINT_DEVICE_IDLE) {
            return "CONSTRAINT_DEVICE_IDLE";
        }
        return "REASON_" + code;
    }

    private static void put(JSONObject object, String key, Object value) {
        try {
            object.put(key, value);
        } catch (Throwable error) {
            throw new IllegalStateException(error);
        }
    }
}
