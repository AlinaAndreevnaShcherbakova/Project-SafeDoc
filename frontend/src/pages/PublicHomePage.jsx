import React from "react";
import Card from "react-bootstrap/Card";
import Col from "react-bootstrap/Col";
import Container from "react-bootstrap/Container";
import Row from "react-bootstrap/Row";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import AppButton from "../components/ui/AppButton";

export default function PublicHomePage() {
  return (
    <Container className="py-5">
      <Row className="justify-content-center">
        <Col md={8} lg={6}>
          <Card>
            <Card.Body>
              <h3 className="mb-3">SafeDoc</h3>
              <p className="text-muted">Платформа для защищенного хранения корпоративного контента и управления доступом.</p>
              <AppButton as={Link} to="/login" variant="primary" icon={ArrowRight}>Перейти ко входу</AppButton>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </Container>
  );
}

