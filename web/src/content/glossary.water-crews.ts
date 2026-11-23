import type { GlossaryEntry } from "./glossary";

export const WATER_CREWS_GLOSSARY = {
  page_water: {
    term: "Water",
    text: "Pressure in each zone, the PS-17 steps in order, boil-water notices and the sensor checks. Every decision named here opens in Decisions.",
  },
  page_crews: {
    term: "Crews",
    text: "Where crews are, the crew plan options compared, damage photos waiting for review, staging yards and generators.",
  },
  pressure_floor: {
    term: "Minimum pressure",
    text: "Lowest pressure allowed at a service connection. Falling below it can trigger a boil-water notice. Each state sets its own minimum.",
  },
  bwa: {
    term: "Boil-water notice",
    text: "Tells customers to boil water before using it. Issued when pressure may be lost; lifted once samples test clean and the regulator agrees.",
  },
  breach_chance: {
    term: "Chance of low pressure",
    text: "Chance that pressure at the most exposed connection drops below the minimum. Above SGW's trigger (policy, not law), a boil-water notice is proposed.",
  },
  sgw_trigger: {
    term: "SGW trigger",
    text: "SGW's own trigger level, set by policy, not by law. Above it, the platform proposes a boil-water notice.",
  },
  recall: {
    term: "Catch rate",
    text: "Share of test faults the checks caught. Missed faults stay hidden, so a low catch rate is a real risk.",
  },
  seeded_faults: {
    term: "Test faults",
    text: "Faults added on purpose to simulated sensor data to see what the checks catch. Not field results.",
  },
  plan_scenarios: {
    term: "Planning for a range of outcomes",
    text: "Each plan is tested against many possible storm sizes, not one average storm. Results are customer-hours of delay, averaged over test storms.",
  },
  customer_hours: {
    term: "Customer-hours",
    text: "Customers without power multiplied by the hours they wait for a crew to arrive. Lower is better.",
  },
  bad_storm: {
    term: "Bad-storm case",
    text: "In 9 of 10 test storms the delay is no larger than this. It shows how bad a poor outcome can get.",
  },
  vss: {
    term: "Saved by planning for the full range",
    text: "Customer-hours saved by planning for the full range of storm outcomes, not just the middle forecast. If small, crew numbers matter more than locations.",
  },
  evpi: {
    term: "Most a perfect forecast could save",
    text: "The most a perfect forecast could save, in customer-hours. If it is small, waiting for a better forecast adds little.",
  },
  plan_envelope: {
    term: "Pre-approved limits",
    text: "How far the crew plan may change. Inside them, one person confirms; outside them, two teams sign again.",
  },
  mutual_aid: {
    term: "Mutual aid",
    text: "Crews lent by other utilities or contractors. Early aid is requested before landfall and is paid for whether or not the storm needs it.",
  },
  idle_crews: {
    term: "Idle early crews",
    text: "Early mutual-aid crews not needed because the storm turned out small. They are still paid.",
  },
  staging_yard: {
    term: "Staging yard",
    text: "A site near likely damage where crews and equipment wait before the storm, ready to move once winds drop.",
  },
  triage_score: {
    term: "Damage score",
    text: "How much damage the model sees in a photo, from 0 to 1. It sets the review order; a person checks every photo.",
  },
  cv_published: {
    term: "Published accuracy",
    text: "Accuracy MIT Lincoln Laboratory reported on its own test photos; SGW didn't measure it. Photos: Civil Air Patrol via MIT Lincoln Laboratory, CC BY 4.0.",
  },
} as const satisfies Record<string, GlossaryEntry>;
