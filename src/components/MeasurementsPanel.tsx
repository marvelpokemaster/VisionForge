import type { Measurement } from "../types/twin";
import type { RoomMeasurementsResponse } from "../lib/api";

interface Props {
  measurements: RoomMeasurementsResponse | null;
}

function MeasurementRow({ label, measurement }: { label: string; measurement: Measurement | null | undefined }) {
  return (
    <tr>
      <td>{label}</td>
      {measurement ? (
        <>
          <td>{measurement.value.toFixed(3)}</td>
          <td>{measurement.units}</td>
          <td>{measurement.method ?? "—"}</td>
        </>
      ) : (
        <td colSpan={3} className="not-measurable">
          not measurable
        </td>
      )}
    </tr>
  );
}

export default function MeasurementsPanel({ measurements }: Props) {
  return (
    <div className="panel">
      <h3>Room Measurements</h3>
      {!measurements ? (
        <p className="muted">Loading...</p>
      ) : (
        <table className="kv measurements">
          <thead>
            <tr>
              <th>Field</th>
              <th>Value</th>
              <th>Units</th>
              <th>Method</th>
            </tr>
          </thead>
          <tbody>
            <MeasurementRow label="Length" measurement={measurements.length} />
            <MeasurementRow label="Width" measurement={measurements.width} />
            <MeasurementRow label="Height" measurement={measurements.height} />
            <MeasurementRow label="Floor area" measurement={measurements.floor_area} />
          </tbody>
        </table>
      )}
    </div>
  );
}
