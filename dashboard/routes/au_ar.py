"""Antibiotic Usage (AU) and Antimicrobial Resistance (AR) reporting routes."""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Add nhsn-reporting to path for nhsn_src package
_nhsn_path = Path(__file__).parent.parent.parent / "nhsn-reporting"
if str(_nhsn_path) not in sys.path:
    sys.path.insert(0, str(_nhsn_path))

from flask import Blueprint, render_template, request, jsonify, current_app, Response

from nhsn_src.db import NHSNDatabase
from nhsn_src.config import Config as NHSNConfig
from nhsn_src.data import AUDataExtractor, ARDataExtractor, DenominatorCalculator

nhsn_reporting_bp = Blueprint("nhsn_reporting", __name__, url_prefix="/nhsn-reporting")


def get_nhsn_db():
    """Get or create NHSN database instance for HAI data."""
    if not hasattr(current_app, "nhsn_db"):
        current_app.nhsn_db = NHSNDatabase(NHSNConfig.NHSN_DB_PATH)
    return current_app.nhsn_db


def get_au_extractor():
    """Get or create AU data extractor instance."""
    if not hasattr(current_app, "au_extractor"):
        current_app.au_extractor = AUDataExtractor()
    return current_app.au_extractor


def get_ar_extractor():
    """Get or create AR data extractor instance."""
    if not hasattr(current_app, "ar_extractor"):
        current_app.ar_extractor = ARDataExtractor()
    return current_app.ar_extractor


def get_denominator_calculator():
    """Get or create denominator calculator instance."""
    if not hasattr(current_app, "denominator_calc"):
        current_app.denominator_calc = DenominatorCalculator()
    return current_app.denominator_calc


@nhsn_reporting_bp.route("/")
def dashboard():
    """AU/AR reporting dashboard overview."""
    try:
        au_extractor = get_au_extractor()
        ar_extractor = get_ar_extractor()
        denom_calc = get_denominator_calculator()

        # Get current month and quarter
        today = date.today()
        current_month = today.strftime("%Y-%m")
        current_quarter = (today.month - 1) // 3 + 1
        current_year = today.year

        # Get date range for current month
        month_start = today.replace(day=1)
        month_end = today

        # Get AU summary for current month (may be empty if no data)
        try:
            au_summary = au_extractor.get_monthly_summary(
                start_date=month_start,
                end_date=month_end,
            )
        except Exception as e:
            current_app.logger.warning(f"AU summary failed: {e}")
            au_summary = {
                "date_range": {"start": str(month_start), "end": str(month_end)},
                "locations": [],
                "overall_totals": {"total_dot": 0, "total_patient_days": 0, "dot_per_1000_pd": 0},
            }

        # Get AR summary for current quarter (may be empty if no data)
        try:
            ar_summary = ar_extractor.get_quarterly_summary(
                year=current_year,
                quarter=current_quarter,
            )
        except Exception as e:
            current_app.logger.warning(f"AR summary failed: {e}")
            ar_summary = {
                "period": {
                    "year": current_year,
                    "quarter": current_quarter,
                    "quarter_string": f"{current_year}-Q{current_quarter}",
                },
                "overall_totals": {"total_cultures": 0, "first_isolates": 0, "unique_organisms": 0},
                "locations": [],
                "phenotypes": [],
            }

        # Get denominator summary (may be empty if no data)
        try:
            denom_summary = denom_calc.get_denominator_summary(
                start_date=month_start,
                end_date=month_end,
            )
        except Exception as e:
            current_app.logger.warning(f"Denominator summary failed: {e}")
            denom_summary = {
                "date_range": {"start": str(month_start), "end": str(month_end)},
                "locations": [],
            }

        return render_template(
            "au_ar_dashboard.html",
            au_summary=au_summary,
            ar_summary=ar_summary,
            denom_summary=denom_summary,
            current_month=current_month,
            current_year=current_year,
            current_quarter=current_quarter,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading AU/AR dashboard: {e}")
        return render_template(
            "au_ar_dashboard.html",
            au_summary=None,
            ar_summary=None,
            denom_summary=None,
            current_month=date.today().strftime("%Y-%m"),
            current_year=date.today().year,
            current_quarter=(date.today().month - 1) // 3 + 1,
            error=str(e),
        )


@nhsn_reporting_bp.route("/au")
def au_detail():
    """Detailed Antibiotic Usage reporting page."""
    try:
        au_extractor = get_au_extractor()

        # Get date range parameters
        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        # Default to last 3 months
        today = date.today()
        if not from_date_str:
            from_date = today.replace(day=1) - timedelta(days=60)
            from_date = from_date.replace(day=1)
        else:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()

        if not to_date_str:
            to_date = today
        else:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

        locations = [location] if location else None

        # Get AU data
        au_summary = au_extractor.get_monthly_summary(
            locations=locations,
            start_date=from_date,
            end_date=to_date,
        )

        # Get category breakdown
        category_df = au_extractor.get_usage_by_category(
            locations=locations,
            start_date=from_date,
            end_date=to_date,
        )
        category_data = category_df.to_dict("records") if not category_df.empty else []

        # Get available locations for filter
        all_locations = set()
        for loc in au_summary.get("locations", []):
            all_locations.add(loc["nhsn_location_code"])

        return render_template(
            "au_detail.html",
            au_summary=au_summary,
            category_data=category_data,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            current_location=location or "",
            available_locations=sorted(all_locations),
        )
    except Exception as e:
        current_app.logger.error(f"Error loading AU detail: {e}")
        today = date.today()
        return render_template(
            "au_detail.html",
            au_summary=None,
            category_data=[],
            from_date=(today - timedelta(days=90)).strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
            current_location="",
            available_locations=[],
            error=str(e),
        )


@nhsn_reporting_bp.route("/ar")
def ar_detail():
    """Detailed Antimicrobial Resistance reporting page."""
    try:
        ar_extractor = get_ar_extractor()

        # Get parameters
        year = request.args.get("year", type=int)
        quarter = request.args.get("quarter", type=int)
        location = request.args.get("location")

        # Default to current quarter
        today = date.today()
        if not year:
            year = today.year
        if not quarter:
            quarter = (today.month - 1) // 3 + 1

        locations = [location] if location else None

        # Get AR data
        ar_summary = ar_extractor.get_quarterly_summary(
            locations=locations,
            year=year,
            quarter=quarter,
        )

        # Get resistance rates
        resistance_df = ar_extractor.calculate_resistance_rates(
            locations=locations,
            year=year,
            quarter=quarter,
        )
        resistance_data = resistance_df.to_dict("records") if not resistance_df.empty else []

        # Get phenotype data
        phenotype_df = ar_extractor.calculate_phenotypes(
            locations=locations,
            year=year,
            quarter=quarter,
        )
        phenotype_data = phenotype_df.to_dict("records") if not phenotype_df.empty else []

        # Available quarters for filter
        quarters = []
        for y in range(year - 1, year + 1):
            for q in range(1, 5):
                if y < year or (y == year and q <= (today.month - 1) // 3 + 1):
                    quarters.append({"year": y, "quarter": q, "label": f"{y}-Q{q}"})

        # Available locations
        all_locations = set()
        for loc in ar_summary.get("locations", []):
            all_locations.add(loc["nhsn_location_code"])

        return render_template(
            "ar_detail.html",
            ar_summary=ar_summary,
            resistance_data=resistance_data,
            phenotype_data=phenotype_data,
            year=year,
            quarter=quarter,
            current_location=location or "",
            available_quarters=quarters,
            available_locations=sorted(all_locations),
        )
    except Exception as e:
        current_app.logger.error(f"Error loading AR detail: {e}")
        today = date.today()
        return render_template(
            "ar_detail.html",
            ar_summary=None,
            resistance_data=[],
            phenotype_data=[],
            year=today.year,
            quarter=(today.month - 1) // 3 + 1,
            current_location="",
            available_quarters=[],
            available_locations=[],
            error=str(e),
        )


@nhsn_reporting_bp.route("/hai")
def hai_detail():
    """HAI events summary for NHSN reporting period."""
    try:
        db = get_nhsn_db()

        # Get date range parameters
        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        hai_type_filter = request.args.get("type")

        # Default to current quarter
        today = date.today()
        if not from_date_str or not to_date_str:
            quarter = (today.month - 1) // 3
            quarter_start_month = quarter * 3 + 1
            from_date = datetime(today.year, quarter_start_month, 1)
            if quarter == 3:
                to_date = datetime(today.year, 12, 31)
            else:
                to_date = datetime(today.year, quarter_start_month + 3, 1) - timedelta(days=1)
        else:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

        # Get summary stats
        stats = db.get_summary_stats()

        # Get confirmed HAI events in date range
        from nhsn_src.models import HAIType
        hai_type = HAIType(hai_type_filter) if hai_type_filter else None
        confirmed_events = db.get_confirmed_hai_in_date_range(from_date, to_date)

        # Filter by type if specified
        if hai_type:
            confirmed_events = [e for e in confirmed_events if e.hai_type == hai_type]

        # Calculate summary by type
        by_type = {}
        by_location = {}
        for event in confirmed_events:
            # By type
            type_key = event.hai_type.value.upper()
            if type_key not in by_type:
                by_type[type_key] = {"count": 0, "organisms": set()}
            by_type[type_key]["count"] += 1
            if event.culture and event.culture.organism:
                by_type[type_key]["organisms"].add(event.culture.organism)

            # By location
            loc = getattr(event, 'location_code', None) or 'Unknown'
            if loc not in by_location:
                by_location[loc] = {"count": 0, "types": set()}
            by_location[loc]["count"] += 1
            by_location[loc]["types"].add(type_key)

        # Convert sets to counts for template
        type_summary = [
            {"type": t, "count": d["count"], "organisms": len(d["organisms"])}
            for t, d in sorted(by_type.items())
        ]
        location_summary = [
            {"location": loc, "count": d["count"], "types": ", ".join(sorted(d["types"]))}
            for loc, d in sorted(by_location.items(), key=lambda x: -x[1]["count"])
        ]

        # Get last submission info
        last_submission = db.get_last_submission()

        # Quarter info for display
        quarter_num = (from_date.month - 1) // 3 + 1
        quarter_label = f"Q{quarter_num} {from_date.year}"

        return render_template(
            "hai_detail.html",
            confirmed_events=confirmed_events,
            type_summary=type_summary,
            location_summary=location_summary,
            total_confirmed=len(confirmed_events),
            stats=stats,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            quarter_label=quarter_label,
            current_type=hai_type_filter or "",
            last_submission=last_submission,
        )

    except Exception as e:
        current_app.logger.error(f"Error loading HAI detail: {e}")
        today = date.today()
        quarter = (today.month - 1) // 3
        quarter_start_month = quarter * 3 + 1
        from_date = datetime(today.year, quarter_start_month, 1)
        return render_template(
            "hai_detail.html",
            confirmed_events=[],
            type_summary=[],
            location_summary=[],
            total_confirmed=0,
            stats={},
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
            quarter_label=f"Q{quarter + 1} {today.year}",
            current_type="",
            last_submission=None,
            error=str(e),
        )


@nhsn_reporting_bp.route("/denominators")
def denominators():
    """Denominator data reporting page (device-days, patient-days)."""
    try:
        denom_calc = get_denominator_calculator()

        # Get date range parameters
        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        # Default to last 3 months
        today = date.today()
        if not from_date_str:
            from_date = today.replace(day=1) - timedelta(days=60)
            from_date = from_date.replace(day=1)
        else:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()

        if not to_date_str:
            to_date = today
        else:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

        locations = [location] if location else None

        # Get denominator summary
        denom_summary = denom_calc.get_denominator_summary(
            locations=locations,
            start_date=from_date,
            end_date=to_date,
        )

        # Get individual data series for detailed view
        patient_days_df = denom_calc.get_patient_days(locations, from_date, to_date)
        line_days_df = denom_calc.get_central_line_days(locations, from_date, to_date)
        catheter_days_df = denom_calc.get_urinary_catheter_days(locations, from_date, to_date)
        vent_days_df = denom_calc.get_ventilator_days(locations, from_date, to_date)

        # Convert to records for template
        patient_days_data = patient_days_df.to_dict("records") if not patient_days_df.empty else []
        line_days_data = line_days_df.to_dict("records") if not line_days_df.empty else []
        catheter_days_data = catheter_days_df.to_dict("records") if not catheter_days_df.empty else []
        vent_days_data = vent_days_df.to_dict("records") if not vent_days_df.empty else []

        # Available locations
        all_locations = set()
        for loc in denom_summary.get("locations", []):
            all_locations.add(loc["nhsn_location_code"])

        return render_template(
            "denominators.html",
            denom_summary=denom_summary,
            patient_days_data=patient_days_data,
            line_days_data=line_days_data,
            catheter_days_data=catheter_days_data,
            vent_days_data=vent_days_data,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            current_location=location or "",
            available_locations=sorted(all_locations),
        )
    except Exception as e:
        current_app.logger.error(f"Error loading denominators: {e}")
        today = date.today()
        return render_template(
            "denominators.html",
            denom_summary=None,
            patient_days_data=[],
            line_days_data=[],
            catheter_days_data=[],
            vent_days_data=[],
            from_date=(today - timedelta(days=90)).strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
            current_location="",
            available_locations=[],
            error=str(e),
        )


# API Endpoints

@nhsn_reporting_bp.route("/api/au/summary")
def api_au_summary():
    """Get AU summary as JSON."""
    try:
        au_extractor = get_au_extractor()

        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date() if from_date_str else None
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date() if to_date_str else None
        locations = [location] if location else None

        summary = au_extractor.get_monthly_summary(locations, from_date, to_date)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_reporting_bp.route("/api/ar/summary")
def api_ar_summary():
    """Get AR summary as JSON."""
    try:
        ar_extractor = get_ar_extractor()

        year = request.args.get("year", type=int)
        quarter = request.args.get("quarter", type=int)
        location = request.args.get("location")

        locations = [location] if location else None

        summary = ar_extractor.get_quarterly_summary(locations, year, quarter)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_reporting_bp.route("/api/denominators")
def api_denominators():
    """Get denominator data as JSON."""
    try:
        denom_calc = get_denominator_calculator()

        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date() if from_date_str else None
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date() if to_date_str else None
        locations = [location] if location else None

        summary = denom_calc.get_denominator_summary(locations, from_date, to_date)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_reporting_bp.route("/api/au/export")
def api_au_export():
    """Export AU data as CSV for NHSN submission."""
    try:
        import csv
        import io

        au_extractor = get_au_extractor()

        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date() if from_date_str else None
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date() if to_date_str else None
        locations = [location] if location else None

        nhsn_df = au_extractor.export_for_nhsn(locations, from_date, to_date)

        if nhsn_df.empty:
            return jsonify({"error": "No data to export"}), 404

        output = io.StringIO()
        nhsn_df.to_csv(output, index=False)
        output.seek(0)

        filename = f"nhsn_au_export_{from_date_str or 'all'}_to_{to_date_str or 'now'}.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_reporting_bp.route("/api/ar/export")
def api_ar_export():
    """Export AR data as CSV for NHSN submission."""
    try:
        import csv
        import io

        ar_extractor = get_ar_extractor()

        year = request.args.get("year", type=int)
        quarter = request.args.get("quarter", type=int)
        location = request.args.get("location")

        locations = [location] if location else None

        export_data = ar_extractor.export_for_nhsn(locations, year, quarter)

        if export_data["isolates"].empty:
            return jsonify({"error": "No data to export"}), 404

        # Create a zip-like response with both CSVs
        output = io.StringIO()
        output.write("# NHSN AR Export - Isolates\n")
        export_data["isolates"].to_csv(output, index=False)
        output.write("\n\n# NHSN AR Export - Susceptibilities\n")
        export_data["susceptibilities"].to_csv(output, index=False)
        output.seek(0)

        filename = f"nhsn_ar_export_{year or 'all'}_Q{quarter or 'all'}.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_reporting_bp.route("/help")
def help_page():
    """AU/AR Help and Demo Guide."""
    return render_template("au_ar_help.html")


@nhsn_reporting_bp.route("/submission")
def submission():
    """Unified NHSN submission page for AU, AR, and HAI data."""
    try:
        # Get parameters
        submission_type = request.args.get("type", "au")  # 'au', 'ar', or 'hai'
        today = date.today()

        if submission_type == "au":
            # AU is monthly
            au_extractor = get_au_extractor()
            from_date_str = request.args.get("from_date")
            to_date_str = request.args.get("to_date")

            if not from_date_str:
                prev_month = today.replace(day=1) - timedelta(days=1)
                from_date = prev_month.replace(day=1)
            else:
                from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()

            if not to_date_str:
                to_date = today.replace(day=1) - timedelta(days=1)
            else:
                to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

            au_summary = au_extractor.get_monthly_summary(start_date=from_date, end_date=to_date)

            return render_template(
                "nhsn_submission_unified.html",
                submission_type="au",
                au_summary=au_summary,
                ar_summary=None,
                hai_events=None,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
                year=None,
                quarter=None,
                preparer_name=request.args.get("preparer_name", ""),
                last_submission=None,
                direct_configured=False,
                direct_config=None,
                audit_log=None,
            )

        elif submission_type == "ar":
            # AR is quarterly
            ar_extractor = get_ar_extractor()
            year = request.args.get("year", type=int) or today.year
            quarter = request.args.get("quarter", type=int)

            if not quarter:
                current_quarter = (today.month - 1) // 3 + 1
                if current_quarter == 1:
                    year -= 1
                    quarter = 4
                else:
                    quarter = current_quarter - 1

            ar_summary = ar_extractor.get_quarterly_summary(year=year, quarter=quarter)

            return render_template(
                "nhsn_submission_unified.html",
                submission_type="ar",
                au_summary=None,
                ar_summary=ar_summary,
                hai_events=None,
                from_date=None,
                to_date=None,
                year=year,
                quarter=quarter,
                preparer_name=request.args.get("preparer_name", ""),
                last_submission=None,
                direct_configured=False,
                direct_config=None,
                audit_log=None,
            )

        else:
            # HAI submission (type='hai')
            db = get_nhsn_db()
            from_date_str = request.args.get("from_date")
            to_date_str = request.args.get("to_date")
            preparer_name = request.args.get("preparer_name", "")

            # Default to current quarter
            if not from_date_str or not to_date_str:
                quarter = (today.month - 1) // 3
                quarter_start_month = quarter * 3 + 1
                from_date = datetime(today.year, quarter_start_month, 1)
                if quarter == 3:
                    to_date = datetime(today.year, 12, 31)
                else:
                    to_date = datetime(today.year, quarter_start_month + 3, 1) - timedelta(days=1)
            else:
                from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
                to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

            # Get confirmed HAI events in date range (always load with default dates)
            events = db.get_confirmed_hai_in_date_range(from_date, to_date)

            # Get audit log and last submission
            audit_log = db.get_submission_audit_log(limit=10)
            last_submission = db.get_last_submission()

            # Check DIRECT configuration
            from nhsn_src.config import Config
            direct_configured = Config.is_direct_configured()
            direct_config = None
            if direct_configured:
                direct_config = {
                    "facility_id": Config.NHSN_FACILITY_ID,
                    "facility_name": Config.NHSN_FACILITY_NAME,
                    "sender_address": Config.NHSN_SENDER_DIRECT_ADDRESS,
                    "nhsn_address": Config.NHSN_DIRECT_ADDRESS,
                }

            return render_template(
                "nhsn_submission_unified.html",
                submission_type="hai",
                au_summary=None,
                ar_summary=None,
                hai_events=events,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
                year=None,
                quarter=None,
                preparer_name=preparer_name,
                last_submission=last_submission,
                direct_configured=direct_configured,
                direct_config=direct_config,
                audit_log=audit_log,
            )

    except Exception as e:
        current_app.logger.error(f"Error loading NHSN submission: {e}")
        today = date.today()
        return render_template(
            "nhsn_submission_unified.html",
            submission_type=request.args.get("type", "au"),
            au_summary=None,
            ar_summary=None,
            hai_events=None,
            from_date=(today.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d"),
            to_date=(today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d"),
            year=today.year,
            quarter=(today.month - 1) // 3 + 1,
            preparer_name="",
            last_submission=None,
            direct_configured=False,
            direct_config=None,
            audit_log=None,
            error=str(e),
        )


# HAI Submission Routes

@nhsn_reporting_bp.route("/submission/hai/export", methods=["POST"])
def hai_export_submission():
    """Export HAI submission data as CSV or PDF."""
    try:
        db = get_nhsn_db()
        import csv
        import io

        from_date_str = request.form.get("from_date")
        to_date_str = request.form.get("to_date")
        preparer_name = request.form.get("preparer_name", "Unknown")
        export_format = request.form.get("format", "csv")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

        events = db.get_confirmed_hai_in_date_range(from_date, to_date)

        # Log the export
        db.log_submission_action(
            action="exported",
            user_name=preparer_name,
            period_start=from_date_str,
            period_end=to_date_str,
            event_count=len(events),
            notes=f"Exported as {export_format.upper()}",
        )

        if export_format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)

            writer.writerow([
                "Event_Date", "Patient_ID", "Patient_Name", "DOB", "Gender",
                "HAI_Type", "Event_Type", "Organism", "Device_Days",
                "Location_Code", "Central_Line_Type", "Notes",
            ])

            for event in events:
                writer.writerow([
                    event.culture.collection_date.strftime("%Y-%m-%d"),
                    event.patient.mrn,
                    event.patient.name or "",
                    event.patient.dob.strftime("%Y-%m-%d") if hasattr(event.patient, 'dob') and event.patient.dob else "",
                    event.patient.gender if hasattr(event.patient, 'gender') else "",
                    event.hai_type.value.upper(),
                    "BSI" if event.hai_type.value == "clabsi" else event.hai_type.value.upper(),
                    event.culture.organism or "",
                    event.device_days_at_culture if event.device_days_at_culture is not None else "",
                    event.location_code if hasattr(event, 'location_code') else "",
                    event.central_line_type if hasattr(event, 'central_line_type') else "",
                    "",
                ])

            output.seek(0)
            filename = f"nhsn_hai_export_{from_date_str}_to_{to_date_str}.csv"
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            # Generate text summary
            content = f"""NHSN HAI Submission Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Prepared by: {preparer_name}
Period: {from_date_str} to {to_date_str}

Total Events: {len(events)}

Event Details:
"""
            for i, event in enumerate(events, 1):
                content += f"""
{i}. {event.hai_type.value.upper()} - {event.culture.collection_date.strftime('%Y-%m-%d')}
   Patient: {event.patient.mrn} ({event.patient.name or 'Unknown'})
   Organism: {event.culture.organism or 'Unknown'}
   Device Days: {event.device_days_at_culture if event.device_days_at_culture is not None else 'N/A'}
"""
            filename = f"nhsn_hai_export_{from_date_str}_to_{to_date_str}.txt"
            return Response(
                content,
                mimetype="text/plain",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

    except Exception as e:
        current_app.logger.error(f"Error exporting HAI data: {e}")
        from flask import redirect, url_for
        return redirect(url_for("nhsn_reporting.submission", type="hai", error=str(e)))


@nhsn_reporting_bp.route("/submission/hai/mark-submitted", methods=["POST"])
def hai_mark_submitted():
    """Mark HAI events as submitted to NHSN."""
    try:
        db = get_nhsn_db()
        from flask import redirect, url_for

        from_date_str = request.form.get("from_date")
        to_date_str = request.form.get("to_date")
        preparer_name = request.form.get("preparer_name", "Unknown")
        notes = request.form.get("notes", "")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

        events = db.get_confirmed_hai_in_date_range(from_date, to_date)
        event_ids = [e.id for e in events]

        db.mark_events_as_submitted(event_ids)

        db.log_submission_action(
            action="submitted",
            user_name=preparer_name,
            period_start=from_date_str,
            period_end=to_date_str,
            event_count=len(events),
            notes=notes,
        )

        return redirect(url_for(
            "nhsn_reporting.submission",
            type="hai",
            from_date=from_date_str,
            to_date=to_date_str,
            preparer_name=preparer_name,
            msg=f"Marked {len(events)} events as submitted"
        ))

    except Exception as e:
        current_app.logger.error(f"Error marking HAI events as submitted: {e}")
        from flask import redirect, url_for
        return redirect(url_for("nhsn_reporting.submission", type="hai", error=str(e)))


@nhsn_reporting_bp.route("/submission/hai/direct", methods=["POST"])
def hai_direct_submission():
    """Submit HAI events directly to NHSN via DIRECT protocol."""
    try:
        db = get_nhsn_db()
        from flask import redirect, url_for

        from_date_str = request.form.get("from_date")
        to_date_str = request.form.get("to_date")
        preparer_name = request.form.get("preparer_name", "Unknown")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

        from nhsn_src.config import Config
        if not Config.is_direct_configured():
            return redirect(url_for(
                "nhsn_reporting.submission",
                type="hai",
                from_date=from_date_str,
                to_date=to_date_str,
                preparer_name=preparer_name,
                error="DIRECT protocol not configured"
            ))

        events = db.get_confirmed_hai_in_date_range(from_date, to_date)
        if not events:
            return redirect(url_for(
                "nhsn_reporting.submission",
                type="hai",
                from_date=from_date_str,
                to_date=to_date_str,
                preparer_name=preparer_name,
                error="No events to submit"
            ))

        from nhsn_src.cda import CDAGenerator, create_bsi_document_from_candidate
        from nhsn_src.direct import DirectClient

        direct_config = Config.get_direct_config()
        generator = CDAGenerator(
            facility_id=direct_config.facility_id,
            facility_name=direct_config.facility_name,
        )

        cda_documents = []
        for event in events:
            bsi_doc = create_bsi_document_from_candidate(
                event,
                facility_id=direct_config.facility_id,
                facility_name=direct_config.facility_name,
                author_name=preparer_name,
            )
            cda_xml = generator.generate_bsi_document(bsi_doc)
            cda_documents.append(cda_xml)

        client = DirectClient(direct_config)
        result = client.submit_cda_documents(
            cda_documents=cda_documents,
            submission_type="HAI-BSI",
            preparer_name=preparer_name,
        )

        if result.success:
            db.log_submission_action(
                action="direct_submitted",
                user_name=preparer_name,
                period_start=from_date_str,
                period_end=to_date_str,
                event_count=len(events),
                notes=f"DIRECT submission. Message ID: {result.message_id}",
            )
            event_ids = [e.id for e in events]
            db.mark_events_as_submitted(event_ids)

            return redirect(url_for(
                "nhsn_reporting.submission",
                type="hai",
                from_date=from_date_str,
                to_date=to_date_str,
                preparer_name=preparer_name,
                msg=f"Submitted {len(events)} events via DIRECT"
            ))
        else:
            return redirect(url_for(
                "nhsn_reporting.submission",
                type="hai",
                from_date=from_date_str,
                to_date=to_date_str,
                preparer_name=preparer_name,
                error=f"DIRECT submission failed: {result.error_message}"
            ))

    except Exception as e:
        current_app.logger.error(f"Error in HAI DIRECT submission: {e}")
        from flask import redirect, url_for
        return redirect(url_for("nhsn_reporting.submission", type="hai", error=str(e)))


@nhsn_reporting_bp.route("/submission/hai/test-direct", methods=["POST"])
def hai_test_direct_connection():
    """Test the DIRECT protocol connection."""
    try:
        from nhsn_src.config import Config
        from nhsn_src.direct import DirectClient

        if not Config.is_direct_configured():
            return jsonify({"success": False, "message": "DIRECT protocol not configured"})

        direct_config = Config.get_direct_config()
        client = DirectClient(direct_config)
        success, message = client.test_connection()

        return jsonify({"success": success, "message": message})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
