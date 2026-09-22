package org.lostboundaries.probe;

import android.app.job.JobParameters;
import android.app.job.JobService;

public final class HoldJobService extends JobService {
    static final String PREFS = "probe";
    static final String CALLBACKS = "callbacks";

    @Override
    public boolean onStartJob(JobParameters params) {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                .putInt(CALLBACKS,
                        getSharedPreferences(PREFS, MODE_PRIVATE).getInt(CALLBACKS, 0) + 1)
                .commit();
        return false;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return false;
    }
}
