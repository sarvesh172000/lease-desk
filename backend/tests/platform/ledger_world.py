"""A tiny company for the gateway and ledger tests, inserted as the owner on
top of the `books` fixture: one clinic, one landlord, January charges, and the
actors that may or may not release a batch.

Work items are inserted directly in whatever state a test needs. The work
layer's transition() is not what is under test here; the gateway is.
"""

from sqlalchemy import text

from app.db.bootstrap import execute_raw

RENT = "CHG-RENT-01"
CAM = "CHG-CAM-01"
RENT_DEC = "CHG-RENT-12"
LATE_FEE = "CHG-LATE-01"
CREDIT = "CHG-CREDIT-01"


def build(owner_engine):
    with owner_engine.begin() as conn:
        execute_raw(conn, """
            INSERT INTO region VALUES ('REG-BAY', 'Bay Area', 'PER-RM-BAY');
            INSERT INTO landlord (id, name) VALUES ('LL-01', 'Harbor Point "Retail" LLC');
            INSERT INTO center VALUES ('CTR-01', 'Harbor Point', NULL, 'LL-01', 20000);
            INSERT INTO clinic VALUES ('CLINIC-01', 'Northbay PT Oakland', 'ENT-CA',
                                       'REG-BAY', 'CTR-01', '110', 2400);
            INSERT INTO lease (id, clinic_id, landlord_id) VALUES ('LEASE-01', 'CLINIC-01', 'LL-01');
            INSERT INTO raw_row VALUES ('RAW-1', 'invoices', '1', '{}');
            INSERT INTO landlord_charge (id, lease_id, clinic_id, invoice_id, suite, period,
                                         charge_type, amount, raw_ref) VALUES
              ('CHG-RENT-01', 'LEASE-01', 'CLINIC-01', 'INV-1', '110', '2026-01-01', 'base_rent', 19626.65, 'RAW-1'),
              ('CHG-CAM-01', 'LEASE-01', 'CLINIC-01', 'INV-1', '110', '2026-01-01', 'cam_estimate', 2100.00, 'RAW-1'),
              ('CHG-RENT-12', 'LEASE-01', 'CLINIC-01', 'INV-0', '110', '2025-12-01', 'base_rent', 19626.65, 'RAW-1'),
              ('CHG-LATE-01', 'LEASE-01', 'CLINIC-01', 'INV-1', '110', '2026-01-01', 'late_fee', 50.00, 'RAW-1'),
              ('CHG-CREDIT-01', 'LEASE-01', 'CLINIC-01', 'INV-1', '110', '2026-01-01', 'base_rent', -10.00, 'RAW-1');
            INSERT INTO entity VALUES ('ENT-NV', 'Northbay PT of Nevada', 'NV');
            INSERT INTO actor (id, name, role, region_id, entity_id, active) VALUES
              ('PER-AP', 'Dana AP', 'ap_clerk', NULL, 'ENT-CA', true),
              ('PER-AP-ALL', 'Lee AP', 'ap_clerk', NULL, NULL, true),
              ('PER-AP-NV', 'Kim AP', 'ap_clerk', NULL, 'ENT-NV', true),
              ('PER-AP-GONE', 'Former AP', 'ap_clerk', NULL, 'ENT-CA', false),
              ('PER-RM-BAY', 'Rita RM', 'regional_manager', 'REG-BAY', 'ENT-CA', true),
              ('PER-CTRL', 'Priya Controller', 'controller', NULL, NULL, true);
        """)


def item(owner_engine, charge_id, state="APPROVED", period="2026-01-01", kind="CHARGE_CHECK",
         subject_type="landlord_charge", entity_id="ENT-CA"):
    with owner_engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO work_item (kind, state, subject_type, subject_id, entity_id,
                                   region_id, clinic_id, period, title)
            VALUES (:kind, :state, :st, :sid, :entity, 'REG-BAY', 'CLINIC-01', :period, :title)
            RETURNING id
        """), dict(kind=kind, state=state, st=subject_type, sid=charge_id, entity=entity_id,
                   period=period, title="check %s" % charge_id)).scalar_one()


def scalar(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()
