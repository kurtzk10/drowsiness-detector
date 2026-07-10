package com.drowsiness.alert;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.RecyclerView;

import java.util.List;

public class EventLogAdapter extends RecyclerView.Adapter<EventLogAdapter.ViewHolder> {

    private final List<Event> events;

    public EventLogAdapter(List<Event> events) {
        this.events = events;
    }

    @NonNull
    @Override
    public ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View v = LayoutInflater.from(parent.getContext())
                .inflate(R.layout.item_event, parent, false);
        return new ViewHolder(v);
    }

    @Override
    public void onBindViewHolder(@NonNull ViewHolder holder, int position) {
        Event event = events.get(position);
        holder.timestamp.setText(event.getFormattedTime());
        holder.duration.setText(event.getFormattedDuration());

        int color;
        switch (event.getType()) {
            case Event.TYPE_DROWSY:
                color = ContextCompat.getColor(holder.itemView.getContext(), android.R.color.holo_red_dark);
                break;
            case Event.TYPE_YAWNING:
                color = ContextCompat.getColor(holder.itemView.getContext(), android.R.color.holo_orange_dark);
                break;
            case Event.TYPE_NOT_LOOKING:
                color = 0xFFFF8844;
                break;
            default:
                color = 0xFF888888;
        }
        holder.dot.setBackgroundColor(color);
    }

    @Override
    public int getItemCount() {
        return events.size();
    }

    static class ViewHolder extends RecyclerView.ViewHolder {
        final View dot;
        final TextView timestamp;
        final TextView duration;

        ViewHolder(View v) {
            super(v);
            dot = v.findViewById(R.id.eventDot);
            timestamp = v.findViewById(R.id.eventTimestamp);
            duration = v.findViewById(R.id.eventDuration);
        }
    }
}
