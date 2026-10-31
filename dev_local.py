"""Disposable, offline local acceptance server. Never uses existing databases."""
import os
os.environ["LOGISTICS_ISOLATED"] = "1"

from app import app, db, User
from models import Customer, CarrierAgent, Shipment, ManualTrack


def seed():
    assert app.config.get("ISOLATED_MODE")
    with app.app_context():
        db.create_all()
        user = User(username="local-admin", is_admin=True)
        user.set_password("local-test-only")
        customer = Customer(name="虚构客户")
        agent = CarrierAgent(name="虚构手工代理", supports_api=False)
        shipment = Shipment(tracking_number="DEMO-001", shipment_id="DEMO-PROVIDER-001",
                            customer=customer, agent=agent, origin="虚构仓库",
                            destination="测试目的地", weight=2, unit_price=10, fee=20)
        db.session.add_all([user, shipment])
        db.session.flush()
        db.session.add(ManualTrack(shipment_id=shipment.id, description="虚构包裹已入库"))
        db.session.commit()


if __name__ == "__main__":
    seed()
    app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)
