from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import ApplianceActivity, AIModel
from ...utils.time import utcnow

router = APIRouter(prefix="/api/v1/appliances", tags=["appliances"])


@router.get("/activity")
def get_appliance_activity(db: Session = Depends(get_db)):
    model = db.query(AIModel).filter(
        AIModel.hardware_validated == True,
        AIModel.status == "PUBLISHED",
    ).order_by(AIModel.created_at.desc()).first()

    if not model:
        return {
            "status": "AI_MODEL_NOT_AVAILABLE",
            "message": "No hardware-validated appliance recognition model available.",
            "real_hardware_validation_required": True,
            "appliances": [],
        }

    latest = (
        db.query(ApplianceActivity)
        .order_by(ApplianceActivity.timestamp.desc())
        .first()
    )

    if not latest:
        return {
            "status": "NO_DATA",
            "message": "No appliance activity recorded.",
            "model_version": model.model_version,
            "appliances": [],
        }

    return {
        "status": "OK",
        "model_version": model.model_version,
        "hardware_validated": model.hardware_validated,
        "timestamp": latest.timestamp.isoformat(),
        "appliances": latest.appliance_states,
        "confidence": latest.confidence,
        "data_source": "AI-INFERRED",
    }


@router.get("/models")
def list_models(db: Session = Depends(get_db)):
    models = db.query(AIModel).order_by(AIModel.created_at.desc()).all()
    return [
        {
            "id": m.id,
            "model_version": m.model_version,
            "model_type": m.model_type,
            "training_source": m.training_source,
            "hardware_validated": m.hardware_validated,
            "status": m.status,
            "accuracy": m.accuracy,
            "created_at": m.created_at.isoformat(),
        }
        for m in models
    ]
